"""保存每位用户每只标的最近一次 AI 分析结果。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Uuid as SqlUuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, EnumValueType
from app.modules.analysis.enums import AIConversationStatus, AIMessageRole, AIMessageStatus


class AIAnalysisReport(Base):
    """缓存最近一次结构化分析，避免重复调用模型产生费用。"""

    __tablename__ = "ai_analysis_reports"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "instrument_id",
            name="uq_ai_analysis_reports_user_instrument",
        ),
        CheckConstraint(
            "provider IN ('openai', 'anthropic')",
            name="ck_ai_analysis_reports_provider",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SqlUuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        SqlUuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    instrument_id: Mapped[UUID] = mapped_column(
        SqlUuid,
        ForeignKey("instruments.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    data_as_of: Mapped[str] = mapped_column(String(40), nullable=False)
    data_sources: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    metrics: Mapped[list[dict[str, str]]] = mapped_column(JSONB, nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class AIConversation(Base):
    """保存用户与 Codex Thread 的一对一会话映射。"""

    __tablename__ = "ai_conversations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('IDLE', 'RUNNING', 'FAILED')",
            name="ck_ai_conversations_status",
        ),
        UniqueConstraint("codex_thread_id", name="uq_ai_conversations_codex_thread_id"),
        Index(
            "ix_ai_conversations_user_instrument_updated",
            "user_id",
            "instrument_id",
            "updated_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SqlUuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        SqlUuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    instrument_id: Mapped[UUID] = mapped_column(
        SqlUuid,
        ForeignKey("instruments.id", ondelete="CASCADE"),
        nullable=False,
    )
    codex_thread_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[AIConversationStatus] = mapped_column(
        EnumValueType(AIConversationStatus, 16),
        nullable=False,
        default=AIConversationStatus.IDLE,
        server_default=AIConversationStatus.IDLE.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AIConversationMessage(Base):
    """按生成顺序保存多轮对话文本，SSE 只负责实时传输。"""

    __tablename__ = "ai_conversation_messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('USER', 'ASSISTANT')",
            name="ck_ai_conversation_messages_role",
        ),
        CheckConstraint(
            "status IN ('STREAMING', 'COMPLETED', 'FAILED')",
            name="ck_ai_conversation_messages_status",
        ),
        Index(
            "ix_ai_conversation_messages_conversation_created",
            "conversation_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SqlUuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    conversation_id: Mapped[UUID] = mapped_column(
        SqlUuid,
        ForeignKey("ai_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[AIMessageRole] = mapped_column(
        EnumValueType(AIMessageRole, 16),
        nullable=False,
    )
    status: Mapped[AIMessageStatus] = mapped_column(
        EnumValueType(AIMessageStatus, 16),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
