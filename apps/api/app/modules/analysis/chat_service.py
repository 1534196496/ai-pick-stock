"""协调 Codex 增量事件、会话串行执行与消息落库。"""

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from app.modules.analysis.agent_runtime import (
    AgentEventKind,
    AgentRuntimeError,
    CodexAgentRuntime,
)
from app.modules.analysis.conversation_repository import AIConversationStore

logger = logging.getLogger(__name__)


class AIStreamEventKind(StrEnum):
    """定义网页 SSE 消费的稳定事件名称。"""

    START = "start"
    STATUS = "status"
    DELTA = "delta"
    DONE = "done"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class AIStreamEvent:
    """保存一个可直接序列化为 SSE data 的事件。"""

    kind: AIStreamEventKind
    payload: dict[str, Any]


class AIConversationAgentService:
    """保证同一会话串行，并让不同会话共享有限并发 Runtime。"""

    def __init__(
        self,
        *,
        store: AIConversationStore,
        runtime: CodexAgentRuntime,
        timeout_seconds: int,
    ) -> None:
        """注入短事务存储、Agent Runtime 和单轮超时。"""
        self._store = store
        self._runtime = runtime
        self._timeout_seconds = timeout_seconds
        self._locks: dict[UUID, asyncio.Lock] = {}

    async def stream_message(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
        content: str,
    ) -> AsyncIterator[AIStreamEvent]:
        """保存用户消息，实时转发 Agent 事件，并最终保存完整回复。"""
        lock = self._locks.setdefault(conversation_id, asyncio.Lock())
        async with lock:
            turn = await self._store.prepare_turn(
                user_id=user_id,
                conversation_id=conversation_id,
                content=content,
            )
            yield AIStreamEvent(
                AIStreamEventKind.START,
                {"assistantMessageId": str(turn.assistant_message_id)},
            )
            yield AIStreamEvent(
                AIStreamEventKind.STATUS,
                {
                    "message": (
                        "正在启动分析 Skill…"
                        if turn.codex_thread_id is None
                        else "正在继续分析…"
                    )
                },
            )
            chunks: list[str] = []
            try:
                async with asyncio.timeout(self._timeout_seconds):
                    async for event in self._runtime.stream_turn(
                        instrument=turn.instrument,
                        codex_thread_id=turn.codex_thread_id,
                        content=content,
                    ):
                        if event.kind is AgentEventKind.THREAD and event.thread_id is not None:
                            await self._store.attach_thread(
                                conversation_id=conversation_id,
                                thread_id=event.thread_id,
                            )
                        elif event.kind is AgentEventKind.STATUS:
                            yield AIStreamEvent(
                                AIStreamEventKind.STATUS,
                                {"message": event.text},
                            )
                        elif event.kind is AgentEventKind.DELTA:
                            chunks.append(event.text)
                            yield AIStreamEvent(
                                AIStreamEventKind.DELTA,
                                {"text": event.text},
                            )
                answer = "".join(chunks).strip()
                if not answer:
                    raise AgentRuntimeError("Agent 没有返回可展示内容")
                await self._store.complete_turn(
                    conversation_id=conversation_id,
                    message_id=turn.assistant_message_id,
                    content=answer,
                )
                yield AIStreamEvent(
                    AIStreamEventKind.DONE,
                    {
                        "assistantMessageId": str(turn.assistant_message_id),
                        "content": answer,
                    },
                )
            except asyncio.CancelledError:
                await self._store.fail_turn(
                    conversation_id=conversation_id,
                    message_id=turn.assistant_message_id,
                    partial_content="".join(chunks),
                )
                raise
            except TimeoutError:
                await self._fail_turn(conversation_id, turn.assistant_message_id, chunks)
                yield AIStreamEvent(
                    AIStreamEventKind.ERROR,
                    {"code": "AI_TURN_TIMEOUT", "message": "分析超时，请重试"},
                )
            except Exception:
                logger.exception(
                    "Codex Agent turn failed",
                    extra={"conversation_id": conversation_id},
                )
                await self._fail_turn(conversation_id, turn.assistant_message_id, chunks)
                yield AIStreamEvent(
                    AIStreamEventKind.ERROR,
                    {"code": "AI_AGENT_UNAVAILABLE", "message": "AI 分析暂时不可用，请重试"},
                )

    async def _fail_turn(
        self,
        conversation_id: UUID,
        message_id: UUID,
        chunks: list[str],
    ) -> None:
        """统一保存流中断前已经展示的部分文本。"""
        await self._store.fail_turn(
            conversation_id=conversation_id,
            message_id=message_id,
            partial_content="".join(chunks),
        )
