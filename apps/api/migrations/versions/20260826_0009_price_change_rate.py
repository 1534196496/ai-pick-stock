"""为行情快照增加今日涨跌率。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_0009"
down_revision: str | None = "20260825_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """增加可空涨跌率，兼容已有价格快照。"""
    op.add_column(
        "instrument_prices",
        sa.Column("change_rate", sa.Numeric(precision=12, scale=8), nullable=True),
    )
    op.create_check_constraint(
        "ck_instrument_prices_change_rate",
        "instrument_prices",
        "change_rate IS NULL OR (change_rate >= -10 AND change_rate <= 10)",
    )


def downgrade() -> None:
    """移除行情涨跌率字段。"""
    op.drop_constraint(
        "ck_instrument_prices_change_rate",
        "instrument_prices",
        type_="check",
    )
    op.drop_column("instrument_prices", "change_rate")
