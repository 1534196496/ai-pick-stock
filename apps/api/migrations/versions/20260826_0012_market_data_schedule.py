"""增加可热更新的行情调度配置。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_0012"
down_revision: str | None = "20260826_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建单例配置并写入推荐的后台任务默认频率。"""
    op.create_table(
        "market_data_schedule",
        sa.Column("id", sa.Integer(), server_default="1", nullable=False),
        sa.Column("stock_refresh_seconds", sa.Integer(), server_default="30", nullable=False),
        sa.Column(
            "fund_estimate_refresh_seconds", sa.Integer(), server_default="60", nullable=False
        ),
        sa.Column(
            "official_nav_refresh_seconds", sa.Integer(), server_default="300", nullable=False
        ),
        sa.Column(
            "official_nav_window_start",
            sa.Time(),
            server_default=sa.text("'16:00:00'"),
            nullable=False,
        ),
        sa.Column(
            "official_nav_window_end",
            sa.Time(),
            server_default=sa.text("'00:30:00'"),
            nullable=False,
        ),
        sa.Column(
            "instrument_sync_time",
            sa.Time(),
            server_default=sa.text("'04:00:00'"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_market_data_schedule_singleton"),
        sa.CheckConstraint(
            "stock_refresh_seconds BETWEEN 15 AND 3600",
            name="ck_market_data_schedule_stock_refresh",
        ),
        sa.CheckConstraint(
            "fund_estimate_refresh_seconds BETWEEN 30 AND 3600",
            name="ck_market_data_schedule_fund_estimate_refresh",
        ),
        sa.CheckConstraint(
            "official_nav_refresh_seconds BETWEEN 120 AND 3600",
            name="ck_market_data_schedule_official_nav_refresh",
        ),
        sa.CheckConstraint("version >= 1", name="ck_market_data_schedule_version"),
        sa.PrimaryKeyConstraint("id", name="pk_market_data_schedule"),
    )
    op.execute("INSERT INTO market_data_schedule (id) VALUES (1)")


def downgrade() -> None:
    """移除行情调度配置并恢复为环境变量静态调度。"""
    op.drop_table("market_data_schedule")
