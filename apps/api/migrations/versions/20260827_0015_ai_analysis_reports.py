"""增加每位用户每只标的最近一次 AI 分析报告。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260827_0015"
down_revision: str | None = "20260826_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建独立报告表，不改变现有持仓、自选和行情结构。"""
    op.create_table(
        "ai_analysis_reports",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("data_as_of", sa.String(length=40), nullable=False),
        sa.Column("data_sources", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "provider IN ('openai', 'anthropic')",
            name="ck_ai_analysis_reports_provider",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name="fk_ai_analysis_reports_instrument_id_instruments",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_ai_analysis_reports_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_analysis_reports"),
        sa.UniqueConstraint(
            "user_id",
            "instrument_id",
            name="uq_ai_analysis_reports_user_instrument",
        ),
    )


def downgrade() -> None:
    """移除 AI 分析报告，不影响任何投资事实与行情数据。"""
    op.drop_table("ai_analysis_reports")
