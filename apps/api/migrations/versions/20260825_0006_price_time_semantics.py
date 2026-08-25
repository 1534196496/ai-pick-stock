"""收紧不同价格类型的业务时间语义。"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260825_0006"
down_revision: str | None = "20260824_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """官方净值只使用业务日期，盘中价格只使用带时区业务时点。"""
    op.create_check_constraint(
        "ck_instrument_prices_time_semantics",
        "instrument_prices",
        "(price_type = 'FUND_OFFICIAL_NAV' "
        "AND as_of_date IS NOT NULL AND as_of_at IS NULL) "
        "OR (price_type IN ('STOCK_LAST', 'FUND_ESTIMATED_NAV') "
        "AND as_of_date IS NULL AND as_of_at IS NOT NULL)",
    )


def downgrade() -> None:
    """移除价格类型与业务时间字段的对应约束。"""
    op.drop_constraint(
        "ck_instrument_prices_time_semantics",
        "instrument_prices",
        type_="check",
    )
