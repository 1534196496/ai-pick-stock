"""修正单基金净值回退源提前一天的历史日期。"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260826_0013"
down_revision: str | None = "20260826_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """清理日期冲突后，将旧版 UTC 解析产生的净值日期统一后移一天。"""
    op.execute(
        """
        DELETE FROM fund_daily_navs AS legacy
        USING fund_daily_navs AS current
        WHERE legacy.source = 'eastmoney_fund_official_single'
          AND current.instrument_id = legacy.instrument_id
          AND current.nav_date = legacy.nav_date + 1
          AND current.source <> 'eastmoney_fund_official_single'
          AND current.id <> legacy.id
        """
    )
    op.execute(
        """
        UPDATE fund_daily_navs
        SET nav_date = nav_date + 10000,
            updated_at = NOW()
        WHERE source = 'eastmoney_fund_official_single'
        """
    )
    op.execute(
        """
        UPDATE fund_daily_navs
        SET nav_date = nav_date - 9999
        WHERE source = 'eastmoney_fund_official_single'
        """
    )


def downgrade() -> None:
    """数据日期纠错不可安全逆转，降级时保留已经修正的真实业务日期。"""
