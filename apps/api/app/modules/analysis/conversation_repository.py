"""AI 多轮会话的用户隔离查询与短事务持久化。"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import case, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.analysis.enums import AIConversationStatus, AIMessageRole, AIMessageStatus
from app.modules.analysis.models import AIConversation, AIConversationMessage
from app.modules.analysis.repository import AnalysisRepository
from app.modules.analysis.schemas import (
    AIConversationMessageResponse,
    AIConversationResponse,
    AnalysisInstrumentResponse,
)
from app.modules.instruments.domain import InstrumentRecord
from app.modules.instruments.models import Instrument


@dataclass(frozen=True, slots=True)
class AIConversationContext:
    """携带已验证归属的会话和标的信息。"""

    conversation: AIConversation
    instrument: InstrumentRecord


@dataclass(frozen=True, slots=True)
class PreparedAgentTurn:
    """记录一次 Agent Turn 开始后需要在流中使用的稳定身份。"""

    conversation_id: UUID
    assistant_message_id: UUID
    codex_thread_id: str | None
    instrument: InstrumentRecord


class AIConversationRepository:
    """在请求事务内读取和创建当前用户的会话。"""

    def __init__(self, session: AsyncSession) -> None:
        """绑定请求级数据库会话。"""
        self._session = session

    async def latest(
        self,
        *,
        user_id: UUID,
        instrument_id: UUID,
    ) -> AIConversationContext | None:
        """读取用户指定标的最近更新的会话。"""
        row = (
            await self._session.execute(
                select(AIConversation, Instrument)
                .join(Instrument, Instrument.id == AIConversation.instrument_id)
                .where(
                    AIConversation.user_id == user_id,
                    AIConversation.instrument_id == instrument_id,
                )
                .order_by(AIConversation.updated_at.desc(), AIConversation.created_at.desc())
                .limit(1)
            )
        ).one_or_none()
        if row is None:
            return None
        conversation, instrument = row
        return AIConversationContext(conversation, _to_instrument(instrument))

    async def create(
        self,
        *,
        user_id: UUID,
        instrument_id: UUID,
    ) -> AIConversationContext:
        """为用户持仓或自选中的股票创建一个独立新会话。"""
        instrument = await AnalysisRepository(self._session).get_tracked_instrument(
            user_id=user_id,
            instrument_id=instrument_id,
        )
        if instrument is None:
            raise LookupError("INSTRUMENT_NOT_TRACKED")
        conversation = AIConversation(
            user_id=user_id,
            instrument_id=instrument_id,
            title=f"{instrument.name} {instrument.ticker}",
            status=AIConversationStatus.IDLE,
        )
        self._session.add(conversation)
        await self._session.flush()
        return AIConversationContext(conversation, instrument)

    async def get_owned(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
    ) -> AIConversationContext | None:
        """按用户隔离读取会话，防止跨账号访问 Thread。"""
        row = (
            await self._session.execute(
                select(AIConversation, Instrument)
                .join(Instrument, Instrument.id == AIConversation.instrument_id)
                .where(
                    AIConversation.id == conversation_id,
                    AIConversation.user_id == user_id,
                )
            )
        ).one_or_none()
        if row is None:
            return None
        conversation, instrument = row
        return AIConversationContext(conversation, _to_instrument(instrument))

    async def messages(self, conversation_id: UUID) -> list[AIConversationMessage]:
        """按创建时间返回会话内的全部消息。"""
        return list(
            (
                await self._session.scalars(
                    select(AIConversationMessage)
                    .where(AIConversationMessage.conversation_id == conversation_id)
                    .order_by(
                        AIConversationMessage.created_at.asc(),
                        case(
                            (AIConversationMessage.role == AIMessageRole.USER, 0),
                            else_=1,
                        ),
                        AIConversationMessage.id.asc(),
                    )
                )
            ).all()
        )


class AIConversationStore:
    """用短事务保存长时间 SSE Turn，避免长期占用请求事务。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """保存应用级数据库会话工厂。"""
        self._session_factory = session_factory

    async def prepare_turn(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
        content: str,
    ) -> PreparedAgentTurn:
        """验证归属并一次性保存用户消息和流式回复占位。"""
        async with self._session_factory() as session, session.begin():
            repository = AIConversationRepository(session)
            context = await repository.get_owned(
                user_id=user_id,
                conversation_id=conversation_id,
            )
            if context is None:
                raise LookupError("AI_CONVERSATION_NOT_FOUND")
            user_message = AIConversationMessage(
                conversation_id=conversation_id,
                role=AIMessageRole.USER,
                status=AIMessageStatus.COMPLETED,
                content=content,
            )
            assistant_message = AIConversationMessage(
                conversation_id=conversation_id,
                role=AIMessageRole.ASSISTANT,
                status=AIMessageStatus.STREAMING,
                content="",
            )
            session.add_all((user_message, assistant_message))
            context.conversation.status = AIConversationStatus.RUNNING
            context.conversation.updated_at = datetime.now(UTC)
            await session.flush()
            return PreparedAgentTurn(
                conversation_id=conversation_id,
                assistant_message_id=assistant_message.id,
                codex_thread_id=context.conversation.codex_thread_id,
                instrument=context.instrument,
            )

    async def attach_thread(self, *, conversation_id: UUID, thread_id: str) -> None:
        """首次启动 Agent 后保存可供后续恢复的 Codex Thread ID。"""
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(AIConversation)
                .where(AIConversation.id == conversation_id)
                .values(codex_thread_id=thread_id, updated_at=datetime.now(UTC))
            )

    async def complete_turn(
        self,
        *,
        conversation_id: UUID,
        message_id: UUID,
        content: str,
    ) -> None:
        """原子完成回复并把会话恢复为空闲状态。"""
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(AIConversationMessage)
                .where(AIConversationMessage.id == message_id)
                .values(content=content, status=AIMessageStatus.COMPLETED)
            )
            await session.execute(
                update(AIConversation)
                .where(AIConversation.id == conversation_id)
                .values(status=AIConversationStatus.IDLE, updated_at=datetime.now(UTC))
            )

    async def fail_turn(
        self,
        *,
        conversation_id: UUID,
        message_id: UUID,
        partial_content: str,
    ) -> None:
        """保留已经流出的文本，并明确标记本轮失败。"""
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(AIConversationMessage)
                .where(AIConversationMessage.id == message_id)
                .values(content=partial_content, status=AIMessageStatus.FAILED)
            )
            await session.execute(
                update(AIConversation)
                .where(AIConversation.id == conversation_id)
                .values(status=AIConversationStatus.FAILED, updated_at=datetime.now(UTC))
            )


async def conversation_response(
    repository: AIConversationRepository,
    context: AIConversationContext,
) -> AIConversationResponse:
    """把会话和消息 ORM 对象转换为稳定公开响应。"""
    messages = await repository.messages(context.conversation.id)
    return AIConversationResponse(
        id=context.conversation.id,
        instrument=AnalysisInstrumentResponse(
            id=context.instrument.id,
            asset_type=context.instrument.asset_type,
            market=context.instrument.market,
            exchange=context.instrument.exchange,
            ticker=context.instrument.ticker,
            name=context.instrument.name,
            currency=context.instrument.currency,
        ),
        title=context.conversation.title,
        status=context.conversation.status,
        messages=[
            AIConversationMessageResponse(
                id=message.id,
                role=message.role,
                status=message.status,
                content=message.content,
                created_at=message.created_at,
            )
            for message in messages
        ],
        created_at=context.conversation.created_at,
        updated_at=context.conversation.updated_at,
    )


def _to_instrument(instrument: Instrument) -> InstrumentRecord:
    """把会话联查得到的 ORM 标的转换为领域记录。"""
    return InstrumentRecord(
        id=instrument.id,
        asset_type=instrument.asset_type,
        market=instrument.market,
        exchange=instrument.exchange,
        ticker=instrument.ticker,
        name=instrument.name,
        currency=instrument.currency,
        source=instrument.source,
        source_updated_at=instrument.source_updated_at,
        updated_at=instrument.updated_at,
    )
