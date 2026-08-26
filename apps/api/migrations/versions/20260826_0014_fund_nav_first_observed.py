"""记录官方基金净值首次同步时间。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_0014"
down_revision: str | None = "20260826_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新增首次同步时间，并保守补齐迁移前无法还原的历史记录。"""
    op.add_column(
        "fund_daily_navs",
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE fund_daily_navs AS nav
        SET first_observed_at = CASE
            WHEN instrument.name ILIKE '%QDII%' THEN nav.fetched_at
            ELSE nav.nav_date::timestamp AT TIME ZONE 'Asia/Shanghai'
        END
        FROM instruments AS instrument
        WHERE instrument.id = nav.instrument_id
          AND nav.first_observed_at IS NULL
        """
    )
    op.alter_column("fund_daily_navs", "first_observed_at", nullable=False)


def downgrade() -> None:
    """移除官方净值首次同步时间。"""
    op.drop_column("fund_daily_navs", "first_observed_at")
