"""通过 Codex App Server 执行 Skill 并产生增量事件。"""

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.modules.instruments.domain import InstrumentRecord
from app.modules.instruments.enums import AssetType

logger = logging.getLogger(__name__)

_PROVIDER_ID = "aipickstock"
_SKILL_NAME_BY_ASSET = {
    AssetType.STOCK: "stock-analysis",
    AssetType.FUND: "fund-analysis",
}


class AgentEventKind(StrEnum):
    """表示 Runtime 向 SSE 编排层暴露的最小事件集合。"""

    THREAD = "THREAD"
    STATUS = "STATUS"
    DELTA = "DELTA"


@dataclass(frozen=True, slots=True)
class AgentRuntimeEvent:
    """屏蔽 Codex 内部协议细节的应用级流事件。"""

    kind: AgentEventKind
    text: str = ""
    thread_id: str | None = None


class AgentRuntimeError(Exception):
    """表示 Codex 进程或本轮分析没有成功完成。"""


class CodexAppServerClient:
    """实现 Codex App Server 的最小异步 JSON-RPC 客户端。"""

    def __init__(
        self,
        *,
        codex_bin: str,
        cwd: Path,
        environment: dict[str, str],
        config_overrides: tuple[str, ...],
    ) -> None:
        """保存进程参数并初始化请求和 Turn 事件路由。"""
        self._codex_bin = codex_bin
        self._cwd = cwd
        self._environment = environment
        self._config_overrides = config_overrides
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._write_lock = asyncio.Lock()
        self._request_id = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._turn_queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self._turn_backlog: dict[str, list[dict[str, Any]]] = {}

    async def start(self) -> None:
        """启动 App Server 并完成 initialize/initialized 握手。"""
        arguments = [self._codex_bin]
        for override in self._config_overrides:
            arguments.extend(("--config", override))
        arguments.extend(("app-server", "--listen", "stdio://"))
        try:
            self._process = await asyncio.create_subprocess_exec(
                *arguments,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._cwd,
                env=self._environment,
            )
        except OSError as error:
            raise AgentRuntimeError("无法启动 Codex Runtime") from error
        self._reader_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        await self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "ai_pick_stock",
                    "title": "AI Pick Stock",
                    "version": "0.1.0",
                },
                "capabilities": {"experimentalApi": True},
            },
        )
        await self.notify("initialized", {})

    async def close(self) -> None:
        """关闭标准输入并在限定时间内回收 App Server。"""
        process = self._process
        if process is None:
            return
        if process.stdin is not None:
            process.stdin.close()
            with suppress(BrokenPipeError):
                await process.stdin.wait_closed()
        try:
            async with asyncio.timeout(5):
                await process.wait()
        except TimeoutError:
            process.terminate()
            await process.wait()
        for task in (self._reader_task, self._stderr_task):
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        self._process = None

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """发送请求并等待对应 ID 的 JSON-RPC 响应。"""
        self._request_id += 1
        request_id = self._request_id
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self._write({"id": request_id, "method": method, "params": params})
            return await future
        finally:
            self._pending.pop(request_id, None)

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        """发送不需要响应的客户端通知。"""
        await self._write({"method": method, "params": params})

    def subscribe_turn(self, turn_id: str) -> asyncio.Queue[dict[str, Any]]:
        """注册 Turn 队列，并转入响应到达前缓存的通知。"""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._turn_queues[turn_id] = queue
        for message in self._turn_backlog.pop(turn_id, []):
            queue.put_nowait(message)
        return queue

    def unsubscribe_turn(self, turn_id: str) -> None:
        """Turn 结束后释放事件队列。"""
        self._turn_queues.pop(turn_id, None)
        self._turn_backlog.pop(turn_id, None)

    async def _write(self, message: dict[str, Any]) -> None:
        """串行写入一行 JSON，避免并发请求互相穿插。"""
        process = self._require_process()
        if process.stdin is None:
            raise AgentRuntimeError("Codex 输入流不可用")
        encoded = (json.dumps(message, ensure_ascii=False) + "\n").encode()
        async with self._write_lock:
            process.stdin.write(encoded)
            try:
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError) as error:
                raise AgentRuntimeError("Codex Runtime 已断开") from error

    async def _read_stdout(self) -> None:
        """持续读取响应，并按请求 ID 或 Turn ID 分发。"""
        process = self._require_process()
        assert process.stdout is not None
        while line := await process.stdout.readline():
            try:
                message = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(message, dict):
                continue
            request_id = message.get("id")
            if isinstance(request_id, int) and ("result" in message or "error" in message):
                self._resolve_response(request_id, message)
                continue
            method = message.get("method")
            if isinstance(request_id, int) and isinstance(method, str):
                await self._deny_server_request(request_id, method)
                continue
            if isinstance(method, str):
                self._route_notification(method, message.get("params"))
        self._fail_pending("Codex Runtime 已退出")

    async def _drain_stderr(self) -> None:
        """消费 stderr 防止子进程管道阻塞，仅记录非敏感摘要。"""
        process = self._require_process()
        assert process.stderr is not None
        while line := await process.stderr.readline():
            if line.strip():
                logger.debug("Codex Runtime emitted a diagnostic line")

    def _resolve_response(self, request_id: int, message: dict[str, Any]) -> None:
        """完成等待中的请求，统一隐藏 Runtime 原始错误细节。"""
        future = self._pending.get(request_id)
        if future is None or future.done():
            return
        result = message.get("result")
        if "error" in message or not isinstance(result, dict):
            future.set_exception(AgentRuntimeError("Codex 请求失败"))
        else:
            future.set_result(result)

    async def _deny_server_request(self, request_id: int, method: str) -> None:
        """拒绝意外审批请求，运行时本身使用 never 策略。"""
        result: dict[str, Any]
        if method in {
            "item/commandExecution/requestApproval",
            "item/fileChange/requestApproval",
        }:
            result = {"decision": "decline"}
        else:
            result = {}
        await self._write({"id": request_id, "result": result})

    def _route_notification(self, method: str, params: object) -> None:
        """只路由带 Turn ID 的通知，忽略与页面无关的全局事件。"""
        if not isinstance(params, dict):
            return
        turn_id = params.get("turnId")
        turn = params.get("turn")
        if not isinstance(turn_id, str) and isinstance(turn, dict):
            candidate = turn.get("id")
            turn_id = candidate if isinstance(candidate, str) else None
        if not isinstance(turn_id, str):
            return
        event = {"method": method, "params": params}
        queue = self._turn_queues.get(turn_id)
        if queue is not None:
            queue.put_nowait(event)
        else:
            self._turn_backlog.setdefault(turn_id, []).append(event)

    def _fail_pending(self, message: str) -> None:
        """进程退出时唤醒所有请求和 Turn 消费者。"""
        error = AgentRuntimeError(message)
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        terminal_event = {"method": "runtime/closed", "params": {}}
        for queue in self._turn_queues.values():
            queue.put_nowait(terminal_event)

    def _require_process(self) -> asyncio.subprocess.Process:
        """返回活动进程，避免生命周期之外调用。"""
        if self._process is None:
            raise AgentRuntimeError("Codex Runtime 尚未启动")
        return self._process


class CodexAgentRuntime:
    """复用一个 Codex App Server，允许不同 Thread 并发执行。"""

    def __init__(self, settings: Settings) -> None:
        """根据全站 OpenAI 兼容配置构造 Runtime，但暂不启动进程。"""
        if not settings.codex_agent_configured:
            raise ValueError("Codex Agent 配置不完整")
        assert settings.ai_api_key is not None
        assert settings.ai_model is not None
        assert settings.resolved_ai_base_url is not None
        self._settings = settings
        self._api_key = settings.ai_api_key.get_secret_value()
        self._model = settings.ai_model.strip()
        self._base_url = settings.resolved_ai_base_url
        self._workspace = Path(settings.ai_agent_workspace).resolve()
        skill_root = Path(settings.ai_agent_skill_root).resolve()
        self._skills = {
            asset_type: skill_root / skill_name / "SKILL.md"
            for asset_type, skill_name in _SKILL_NAME_BY_ASSET.items()
        }
        self._prompt_spec = Path(settings.ai_agent_prompt_spec_path).resolve()
        self._capacity = asyncio.Semaphore(settings.ai_agent_max_concurrency)
        self._client: CodexAppServerClient | None = None

    async def start(self) -> None:
        """校验 Skill 资产并启动 Codex App Server。"""
        for asset_type, skill_path in self._skills.items():
            if not skill_path.is_file():
                raise RuntimeError(f"缺少 {asset_type.value} 分析 Skill：{skill_path}")
        if not self._prompt_spec.is_file():
            raise RuntimeError(f"缺少投资分析 Prompt 规范：{self._prompt_spec}")
        self._workspace.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment["AIPICKSTOCK_CODEX_API_KEY"] = self._api_key
        self._client = CodexAppServerClient(
            codex_bin=self._settings.ai_agent_codex_bin or "codex",
            cwd=self._workspace,
            environment=environment,
            config_overrides=(
                f'model_provider="{_PROVIDER_ID}"',
                f'model_reasoning_effort="{self._settings.ai_agent_reasoning_effort}"',
                'web_search="live"',
                'agents.enabled=false',
                'shell_environment_policy.inherit="all"',
                (
                    "shell_environment_policy.set.PATH="
                    f"{json.dumps(environment.get('PATH', ''), ensure_ascii=False)}"
                ),
                f'model_providers.{_PROVIDER_ID}.name="AI Pick Stock Proxy"',
                (
                    f"model_providers.{_PROVIDER_ID}.base_url="
                    f"{json.dumps(self._base_url, ensure_ascii=False)}"
                ),
                (
                    f'model_providers.{_PROVIDER_ID}.env_key='
                    '"AIPICKSTOCK_CODEX_API_KEY"'
                ),
                f'model_providers.{_PROVIDER_ID}.wire_api="responses"',
                f"model_providers.{_PROVIDER_ID}.requires_openai_auth=false",
            ),
        )
        await self._client.start()
        skill_root = str(next(iter(self._skills.values())).parent.parent)
        await self._client.request(
            "skills/extraRoots/set",
            {"extraRoots": [skill_root]},
        )
        discovered = await self._client.request(
            "skills/list",
            {"cwds": [str(self._workspace)], "forceReload": True},
        )
        for asset_type, skill_name in _SKILL_NAME_BY_ASSET.items():
            if not _contains_enabled_skill(discovered, skill_name):
                await self._client.close()
                self._client = None
                raise RuntimeError(
                    f"Codex 未发现 {asset_type.value} 分析 Skill：{self._skills[asset_type]}"
                )

    async def close(self) -> None:
        """停止 App Server 子进程并释放事件路由资源。"""
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def stream_turn(
        self,
        *,
        instrument: InstrumentRecord,
        codex_thread_id: str | None,
        content: str,
    ) -> AsyncIterator[AgentRuntimeEvent]:
        """启动或恢复 Thread，并把 Codex 通知转换为可展示事件。"""
        skill_name = _SKILL_NAME_BY_ASSET.get(instrument.asset_type)
        skill_path = self._skills.get(instrument.asset_type)
        if skill_name is None or skill_path is None:
            raise AgentRuntimeError("当前标的类型尚未启用 Skill 多轮分析")
        client = self._require_client()
        async with self._capacity:
            thread_id = codex_thread_id
            if thread_id is None:
                started = await client.request(
                    "thread/start",
                    {
                        "approvalPolicy": "never",
                        "cwd": str(self._workspace),
                        "developerInstructions": _developer_instructions(
                            self._prompt_spec
                        ),
                        "ephemeral": False,
                        "model": self._model,
                        "modelProvider": _PROVIDER_ID,
                        "sandbox": "danger-full-access",
                    },
                )
                thread_id = _nested_string(started, "thread", "id")
                yield AgentRuntimeEvent(AgentEventKind.THREAD, thread_id=thread_id)
                run_input: list[dict[str, str]] = [
                    {
                        "type": "skill",
                        "name": skill_name,
                        "path": str(skill_path),
                    },
                    {
                        "type": "text",
                        "text": _first_turn_prompt(instrument, content, skill_name),
                    },
                ]
            else:
                await client.request(
                    "thread/resume",
                    {
                        "threadId": thread_id,
                        "approvalPolicy": "never",
                        "cwd": str(self._workspace),
                        "model": self._model,
                        "modelProvider": _PROVIDER_ID,
                        "sandbox": "danger-full-access",
                    },
                )
                run_input = [{"type": "text", "text": content}]

            started_turn = await client.request(
                "turn/start",
                {
                    "threadId": thread_id,
                    "input": run_input,
                    "approvalPolicy": "never",
                    "effort": self._settings.ai_agent_reasoning_effort,
                    "sandboxPolicy": {"type": "dangerFullAccess"},
                },
            )
            turn_id = _nested_string(started_turn, "turn", "id")
            queue = client.subscribe_turn(turn_id)
            completed = False
            try:
                while True:
                    notification = await queue.get()
                    method = notification.get("method")
                    params = notification.get("params")
                    if not isinstance(params, dict):
                        if method == "runtime/closed":
                            raise AgentRuntimeError("Codex Runtime 已退出")
                        continue
                    if method == "item/agentMessage/delta":
                        delta = params.get("delta")
                        if isinstance(delta, str) and delta:
                            yield AgentRuntimeEvent(AgentEventKind.DELTA, text=delta)
                    elif method == "item/started":
                        status = _item_status(params)
                        if status is not None:
                            yield AgentRuntimeEvent(AgentEventKind.STATUS, text=status)
                    elif method == "error" and params.get("willRetry") is True:
                        yield AgentRuntimeEvent(
                            AgentEventKind.STATUS,
                            text="模型连接波动，正在自动重试…",
                        )
                    elif method == "turn/completed":
                        completed = _nested_string(params, "turn", "status") == "completed"
                        if not completed:
                            raise AgentRuntimeError("Codex 本轮分析未完成")
                        break
            finally:
                client.unsubscribe_turn(turn_id)
                if not completed:
                    with suppress(Exception):
                        await client.request(
                            "turn/interrupt",
                            {"threadId": thread_id, "turnId": turn_id},
                        )

    def _require_client(self) -> CodexAppServerClient:
        """返回已启动的 Runtime，防止生命周期之外调用。"""
        if self._client is None:
            raise AgentRuntimeError("Codex Agent 尚未启动")
        return self._client


def create_codex_agent_runtime(settings: Settings) -> CodexAgentRuntime | None:
    """只在 OpenAI Responses 配置完整时启用 Codex Agent。"""
    if not settings.codex_agent_configured:
        return None
    return CodexAgentRuntime(settings)


def _first_turn_prompt(
    instrument: InstrumentRecord,
    content: str,
    skill_name: str,
) -> str:
    """把页面的简短动作转换为明确的首次 Skill 任务。"""
    asset_label = "基金" if instrument.asset_type is AssetType.FUND else "股票"
    data_task = (
        "由 Skill 自己获取官方历史净值，计算阶段收益、波动和回撤；本轮不要搜索新闻或公告。"
        if instrument.asset_type is AssetType.FUND
        else "由 Skill 自己获取最新行情、历史数据和新闻，完成指标计算后输出决策看板。"
    )
    return (
        f"{content}\n\n"
        f"请严格执行已附加的 ${skill_name} Skill，分析{asset_label} "
        f"{instrument.ticker}（{instrument.name}）。"
        f"{data_task}按照投资分析总规范明确给出行动结论、置信度、核心证据、"
        "反方证据、风险和判断失效条件；数据缺失的维度直接列入限制。"
    )


def _developer_instructions(prompt_spec_path: Path) -> str:
    """要求每个新 Session 采用项目投资分析规范，同时保留 SSE 对话输出。"""
    return (
        "始终使用简体中文回答。首次分析前必须完整读取投资分析总规范："
        f"{prompt_spec_path}。将其分析纪律与当前标的 Skill 共同执行。"
        "当前产品采用 Codex Skill + SSE 多轮对话，按以下规则适配该规范："
        "Skill 实际获取并计算的结构化结果视为本轮 AnalysisInput，除此之外不得补充"
        "未经核实的行情、净值、新闻、资金、财报或持仓事实；缺失字段必须明确说明。"
        "必须执行规范中的事实边界、数据口径、1/5/20/60 日窗口、股票基金分流、"
        "反方验证、行动结论、置信度和产品展示纪律。重要判断必须关联实际数据日期、"
        "来源或可核验指标，不得编造 evidenceId。"
        "最终按规范第 7 节的阅读顺序输出简洁 Markdown，不展示隐藏思维过程；"
        "当前聊天界面不强制输出第 6 节 JSON，除非用户明确要求 JSON。"
        "所有行情、净值和新闻结论必须来自 Skill 实际获取的数据；"
        "数据缺失时明确说明，宁可不知道也不得编造。"
    )


def _item_status(params: dict[str, Any]) -> str | None:
    """把内部工具项目映射为不暴露命令细节的产品状态。"""
    item = params.get("item")
    item_type = item.get("type") if isinstance(item, dict) else None
    if item_type == "commandExecution":
        return "正在获取行情并计算技术指标…"
    if item_type == "webSearch":
        return "正在搜索和核对最新消息…"
    if item_type == "reasoning":
        return "正在综合分析数据…"
    return None


def _nested_string(value: dict[str, Any], parent: str, key: str) -> str:
    """从 Runtime 响应中读取必需字符串，缺失时立即失败。"""
    nested = value.get(parent)
    result = nested.get(key) if isinstance(nested, dict) else None
    if not isinstance(result, str) or not result:
        raise AgentRuntimeError("Codex 响应缺少必要字段")
    return result


def _contains_enabled_skill(response: dict[str, Any], skill_name: str) -> bool:
    """确认 App Server 已发现并启用指定 Skill。"""
    data = response.get("data")
    if not isinstance(data, list):
        return False
    for entry in data:
        skills = entry.get("skills") if isinstance(entry, dict) else None
        if not isinstance(skills, list):
            continue
        if any(
            isinstance(skill, dict)
            and skill.get("name") == skill_name
            and skill.get("enabled") is True
            for skill in skills
        ):
            return True
    return False
