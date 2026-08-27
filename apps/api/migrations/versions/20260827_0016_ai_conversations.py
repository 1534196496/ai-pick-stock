"""增加 Codex 多轮会话与消息记录。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_0016"
down_revision: str | None = "20260827_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建轻量会话表和消息表，不改变已有单次分析接口。"""
    op.create_table(
        "ai_conversations",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("codex_thread_id", sa.String(length=80), nullable=True),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="IDLE", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('IDLE', 'RUNNING', 'FAILED')",
            name="ck_ai_conversations_status",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name="fk_ai_conversations_instrument_id_instruments",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_ai_conversations_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_conversations"),
        sa.UniqueConstraint(
            "codex_thread_id",
            name="uq_ai_conversations_codex_thread_id",
        ),
    )
    op.create_index(
        "ix_ai_conversations_user_instrument_updated",
        "ai_conversations",
        ["user_id", "instrument_id", "updated_at"],
    )
    op.create_table(
        "ai_conversation_messages",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "role IN ('USER', 'ASSISTANT')",
            name="ck_ai_conversation_messages_role",
        ),
        sa.CheckConstraint(
            "status IN ('STREAMING', 'COMPLETED', 'FAILED')",
            name="ck_ai_conversation_messages_status",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["ai_conversations.id"],
            name="fk_ai_conversation_messages_conversation_id_ai_conversations",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_conversation_messages"),
    )
    op.create_index(
        "ix_ai_conversation_messages_conversation_created",
        "ai_conversation_messages",
        ["conversation_id", "created_at"],
    )


def downgrade() -> None:
    """移除会话功能，不触碰已有报告和投资数据。"""
    op.drop_index(
        "ix_ai_conversation_messages_conversation_created",
        table_name="ai_conversation_messages",
    )
    op.drop_table("ai_conversation_messages")
    op.drop_index(
        "ix_ai_conversations_user_instrument_updated",
        table_name="ai_conversations",
    )
    op.drop_table("ai_conversations")
