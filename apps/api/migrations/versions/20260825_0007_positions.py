"""创建保留原始输入和规范化结果的用户持仓表。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0007"
down_revision: str | None = "20260825_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """建立账户内唯一、输入形状、推算依据和乐观锁约束。"""
    op.create_table(
        "positions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("input_mode", sa.String(length=24), nullable=False),
        sa.Column("cost_input_mode", sa.String(length=16), nullable=True),
        sa.Column("input_date", sa.Date(), nullable=False),
        sa.Column("input_quantity", sa.Numeric(precision=28, scale=8), nullable=True),
        sa.Column("input_total_cost", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("input_average_cost", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("input_current_value", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("input_holding_profit", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=28, scale=8), nullable=True),
        sa.Column("total_cost", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("average_cost", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column(
            "quantity_estimated",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("quantity_basis_nav", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("quantity_basis_nav_date", sa.Date(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "input_mode IN ('STOCK_SHARES', 'FUND_AMOUNT', 'FUND_SHARES')",
            name="position_input_mode",
        ),
        sa.CheckConstraint(
            "cost_input_mode IS NULL OR cost_input_mode IN ('TOTAL_COST', 'AVERAGE_COST')",
            name="cost_input_mode",
        ),
        sa.CheckConstraint("version >= 1", name="ck_positions_version"),
        sa.CheckConstraint(
            "input_quantity IS NULL OR input_quantity > 0",
            name="ck_positions_input_quantity",
        ),
        sa.CheckConstraint(
            "input_total_cost IS NULL OR input_total_cost > 0",
            name="ck_positions_input_total_cost",
        ),
        sa.CheckConstraint(
            "input_average_cost IS NULL OR input_average_cost > 0",
            name="ck_positions_input_average_cost",
        ),
        sa.CheckConstraint(
            "input_current_value IS NULL OR input_current_value > 0",
            name="ck_positions_input_current_value",
        ),
        sa.CheckConstraint("quantity IS NULL OR quantity > 0", name="ck_positions_quantity"),
        sa.CheckConstraint("total_cost > 0", name="ck_positions_total_cost"),
        sa.CheckConstraint(
            "average_cost IS NULL OR average_cost > 0",
            name="ck_positions_average_cost",
        ),
        sa.CheckConstraint(
            "(quantity IS NULL AND average_cost IS NULL) OR "
            "(quantity IS NOT NULL AND average_cost IS NOT NULL)",
            name="ck_positions_quantity_average_cost",
        ),
        sa.CheckConstraint(
            "(quantity_estimated IS FALSE AND quantity_basis_nav IS NULL "
            "AND quantity_basis_nav_date IS NULL "
            "AND (input_mode <> 'FUND_AMOUNT' OR quantity IS NULL)) OR "
            "(quantity_estimated IS TRUE AND input_mode = 'FUND_AMOUNT' "
            "AND quantity IS NOT NULL AND quantity_basis_nav > 0 "
            "AND quantity_basis_nav_date IS NOT NULL)",
            name="ck_positions_quantity_estimation",
        ),
        sa.CheckConstraint(
            "((input_mode IN ('STOCK_SHARES', 'FUND_SHARES')) "
            "AND input_quantity IS NOT NULL AND input_current_value IS NULL "
            "AND input_holding_profit IS NULL "
            "AND ((cost_input_mode = 'TOTAL_COST' AND input_total_cost IS NOT NULL "
            "AND input_average_cost IS NULL) OR "
            "(cost_input_mode = 'AVERAGE_COST' AND input_average_cost IS NOT NULL "
            "AND input_total_cost IS NULL))) OR "
            "(input_mode = 'FUND_AMOUNT' AND cost_input_mode IS NULL "
            "AND input_quantity IS NULL AND input_total_cost IS NULL "
            "AND input_average_cost IS NULL AND input_current_value IS NOT NULL "
            "AND input_holding_profit IS NOT NULL)",
            name="ck_positions_input_shape",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["investment_accounts.id"],
            name="fk_positions_account_id_investment_accounts",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name="fk_positions_instrument_id_instruments",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_positions"),
        sa.UniqueConstraint(
            "account_id",
            "instrument_id",
            name="uq_positions_account_instrument",
        ),
    )
    op.create_index(
        "ix_positions_account_created",
        "positions",
        ["account_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_positions_instrument",
        "positions",
        ["instrument_id"],
        unique=False,
    )


def downgrade() -> None:
    """移除持仓表及其索引。"""
    op.drop_index("ix_positions_instrument", table_name="positions")
    op.drop_index("ix_positions_account_created", table_name="positions")
    op.drop_table("positions")
