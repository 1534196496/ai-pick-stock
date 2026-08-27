"""OpenAI Chat Completions 与 Claude Messages 兼容协议适配。"""

import json
from typing import Any, Protocol, cast

import httpx
from pydantic import ValidationError

from app.core.config import Settings
from app.modules.analysis.schemas import GeneratedAnalysis


class AIProviderError(Exception):
    """表示模型调用失败且不应向客户端暴露原始响应。"""


class AIProviderAuthenticationError(AIProviderError):
    """表示全站模型 Key 或兼容地址配置无效。"""


class AIProviderUnavailableError(AIProviderError):
    """表示模型超时、限流或服务暂时不可用。"""


class AIProviderPayloadError(AIProviderError):
    """表示模型返回内容不符合结构化分析契约。"""


class AIModelClient(Protocol):
    """隔离分析服务与具体模型协议。"""

    provider: str
    model: str

    async def generate(self, *, system_prompt: str, user_prompt: str) -> GeneratedAnalysis:
        """根据严格提示生成并校验结构化分析。"""
        ...


class CompatibleAIClient:
    """使用共享 HTTP 连接池调用全站唯一模型配置。"""

    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: int,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """保存非空配置，并允许测试替换 HTTP 客户端。"""
        self.provider = provider
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds, connect=10),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
            trust_env=False,
        )

    async def generate(self, *, system_prompt: str, user_prompt: str) -> GeneratedAnalysis:
        """按配置协议调用模型，并把任意第三方响应收敛为固定结构。"""
        try:
            if self.provider == "openai":
                text = await self._generate_openai(system_prompt, user_prompt)
            else:
                text = await self._generate_anthropic(system_prompt, user_prompt)
            return _parse_generated_analysis(text)
        except AIProviderError:
            raise
        except (httpx.TimeoutException, httpx.TransportError) as error:
            raise AIProviderUnavailableError("模型服务连接失败") from error

    async def close(self) -> None:
        """只关闭由当前适配器创建的连接池。"""
        if self._owns_client:
            await self._client.aclose()

    async def _generate_openai(self, system_prompt: str, user_prompt: str) -> str:
        """调用 OpenAI Chat Completions 兼容接口并提取文本。"""
        payload = _openai_payload(
            model=self.model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        response = await self._client.post(
            _endpoint(self._base_url, "/chat/completions"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        _raise_for_provider_status(response)
        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("模型文本为空")
            return content
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as error:
            raise AIProviderPayloadError("OpenAI 兼容响应结构异常") from error

    async def _generate_anthropic(self, system_prompt: str, user_prompt: str) -> str:
        """调用 Claude Messages 兼容接口并合并文本内容块。"""
        response = await self._client.post(
            _endpoint(self._base_url, "/v1/messages"),
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
                "temperature": 0.2,
                "max_tokens": 1800,
            },
        )
        _raise_for_provider_status(response)
        try:
            payload = response.json()
            blocks = payload["content"]
            text = "".join(
                str(block["text"])
                for block in blocks
                if isinstance(block, dict) and block.get("type") == "text"
            )
            if not text.strip():
                raise ValueError("模型文本为空")
            return text
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise AIProviderPayloadError("Claude 兼容响应结构异常") from error


def create_ai_model_client(settings: Settings) -> CompatibleAIClient | None:
    """仅在全站模型配置完整时创建共享适配器。"""
    if not settings.ai_configured:
        return None
    assert settings.ai_provider is not None
    assert settings.ai_api_key is not None
    assert settings.ai_model is not None
    assert settings.resolved_ai_base_url is not None
    return CompatibleAIClient(
        provider=settings.ai_provider,
        base_url=settings.resolved_ai_base_url,
        api_key=settings.ai_api_key.get_secret_value(),
        model=settings.ai_model.strip(),
        timeout_seconds=settings.ai_timeout_seconds,
    )


def _endpoint(base_url: str, suffix: str) -> str:
    """兼容传入服务根地址、v1 根地址或完整接口地址。"""
    base = base_url.rstrip("/")
    if base.endswith(suffix):
        return base
    if suffix.startswith("/v1/") and base.endswith("/v1"):
        return base + suffix.removeprefix("/v1")
    return base + suffix


def _openai_payload(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any]:
    """为 GPT-5.6 使用新版参数，同时保留其他兼容服务的通用请求。"""
    if model == "gpt-5.6-sol" or model == "gpt-5.6":
        return {
            "model": model,
            "messages": [
                {"role": "developer", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "reasoning_effort": "low",
            "max_completion_tokens": 3000,
            "response_format": {"type": "json_object"},
        }
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 1800,
    }


def _raise_for_provider_status(response: httpx.Response) -> None:
    """把模型状态码分类为鉴权、暂时不可用或通用响应错误。"""
    if response.status_code in {401, 403}:
        raise AIProviderAuthenticationError("模型鉴权失败")
    if response.status_code == 429 or response.status_code >= 500:
        raise AIProviderUnavailableError("模型服务暂时不可用")
    if response.is_error:
        raise AIProviderPayloadError("模型服务拒绝了分析请求")


def _parse_generated_analysis(text: str) -> GeneratedAnalysis:
    """从纯 JSON 或带代码块的兼容模型文本中提取并校验对象。"""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.removeprefix("```json").removeprefix("```")
        stripped = stripped.removesuffix("```").strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise AIProviderPayloadError("模型没有返回 JSON 对象")
    try:
        payload = cast(dict[str, Any], json.loads(stripped[start : end + 1]))
        return GeneratedAnalysis.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, TypeError) as error:
        raise AIProviderPayloadError("模型分析结果字段不完整") from error
