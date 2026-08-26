"""精简持仓主表，并按数据形态拆分交易与行情历史。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_0011"
down_revision: str | None = "20260826_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """迁移现有数据后切换到精简、可扩展的组合数据模型。"""
    _rename_group_table()
    _create_market_tables()
    _migrate_market_data()
    _refactor_positions()
    op.drop_table("instrument_prices")


def downgrade() -> None:
    """重建旧价格与持仓输入结构，并恢复原分组表名。"""
    _restore_instrument_prices()
    _restore_position_inputs()
    op.drop_table("position_daily_snapshots")
    op.drop_table("stock_daily_bars")
    op.drop_table("fund_daily_navs")
    op.drop_table("intraday_quotes")
    op.drop_table("latest_quotes")
    _restore_group_table_name()


def _rename_group_table() -> None:
    """把同时承载持仓和自选的分组改为准确的组合分组名称。"""
    op.rename_table("watchlist_groups", "portfolio_groups")
    renames = (
        ("portfolio_groups", "pk_watchlist_groups", "pk_portfolio_groups"),
        (
            "portfolio_groups",
            "fk_watchlist_groups_user_id_users",
            "fk_portfolio_groups_user_id_users",
        ),
        (
            "portfolio_groups",
            "uq_watchlist_groups_user_name",
            "uq_portfolio_groups_user_name",
        ),
        ("portfolio_groups", "ck_watchlist_groups_name", "ck_portfolio_groups_name"),
        (
            "portfolio_groups",
            "ck_watchlist_groups_sort_order",
            "ck_portfolio_groups_sort_order",
        ),
        (
            "portfolio_groups",
            "ck_watchlist_groups_version",
            "ck_portfolio_groups_version",
        ),
        (
            "watchlist_items",
            "fk_watchlist_items_group_id_watchlist_groups",
            "fk_watchlist_items_group_id_portfolio_groups",
        ),
        (
            "positions",
            "fk_positions_group_id_watchlist_groups",
            "fk_positions_group_id_portfolio_groups",
        ),
    )
    for table, old_name, new_name in renames:
        op.execute(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{old_name}" TO "{new_name}"')
    op.execute(
        "ALTER INDEX uq_watchlist_groups_one_default RENAME TO uq_portfolio_groups_one_default"
    )
    op.execute("ALTER INDEX ix_watchlist_groups_user_sort RENAME TO ix_portfolio_groups_user_sort")


def _create_market_tables() -> None:
    """分别创建最新行情、盘中历史、股票日线和基金净值表。"""
    op.create_table(
        "latest_quotes",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("quote_type", sa.String(length=32), nullable=False),
        sa.Column("value", sa.Numeric(24, 8), nullable=False),
        sa.Column("change_rate", sa.Numeric(12, 8), nullable=True),
        sa.Column("quoted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "quote_type IN ('STOCK_LAST', 'FUND_ESTIMATED_NAV')",
            name="ck_latest_quotes_type",
        ),
        sa.CheckConstraint("value > 0", name="ck_latest_quotes_value"),
        sa.CheckConstraint(
            "change_rate IS NULL OR change_rate BETWEEN -10 AND 10",
            name="ck_latest_quotes_change_rate",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name="fk_latest_quotes_instrument_id_instruments",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_latest_quotes"),
        sa.UniqueConstraint("instrument_id", "quote_type", name="uq_latest_quotes_instrument_type"),
    )
    op.create_index("ix_latest_quotes_quoted_at", "latest_quotes", ["quote_type", "quoted_at"])

    op.create_table(
        "intraday_quotes",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("quote_type", sa.String(length=32), nullable=False),
        sa.Column("value", sa.Numeric(24, 8), nullable=False),
        sa.Column("change_rate", sa.Numeric(12, 8), nullable=True),
        sa.Column("quoted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.CheckConstraint(
            "quote_type IN ('STOCK_LAST', 'FUND_ESTIMATED_NAV')",
            name="ck_intraday_quotes_type",
        ),
        sa.CheckConstraint("value > 0", name="ck_intraday_quotes_value"),
        sa.CheckConstraint(
            "change_rate IS NULL OR change_rate BETWEEN -10 AND 10",
            name="ck_intraday_quotes_change_rate",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name="fk_intraday_quotes_instrument_id_instruments",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_intraday_quotes"),
        sa.UniqueConstraint(
            "instrument_id",
            "quote_type",
            "quoted_at",
            "source",
            name="uq_intraday_quotes_point",
        ),
    )
    op.create_index(
        "ix_intraday_quotes_instrument_time",
        "intraday_quotes",
        ["instrument_id", "quote_type", "quoted_at"],
    )

    op.create_table(
        "fund_daily_navs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("nav_date", sa.Date(), nullable=False),
        sa.Column("unit_nav", sa.Numeric(24, 8), nullable=False),
        sa.Column("accumulated_nav", sa.Numeric(24, 8), nullable=True),
        sa.Column("daily_return_rate", sa.Numeric(12, 8), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("unit_nav > 0", name="ck_fund_daily_navs_unit_nav"),
        sa.CheckConstraint(
            "accumulated_nav IS NULL OR accumulated_nav > 0",
            name="ck_fund_daily_navs_accumulated_nav",
        ),
        sa.CheckConstraint(
            "daily_return_rate IS NULL OR daily_return_rate BETWEEN -10 AND 10",
            name="ck_fund_daily_navs_return_rate",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name="fk_fund_daily_navs_instrument_id_instruments",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_fund_daily_navs"),
        sa.UniqueConstraint("instrument_id", "nav_date", name="uq_fund_daily_navs_instrument_date"),
    )
    op.create_index(
        "ix_fund_daily_navs_instrument_date",
        "fund_daily_navs",
        ["instrument_id", "nav_date"],
    )

    op.create_table(
        "stock_daily_bars",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(24, 8), nullable=False),
        sa.Column("high", sa.Numeric(24, 8), nullable=False),
        sa.Column("low", sa.Numeric(24, 8), nullable=False),
        sa.Column("close", sa.Numeric(24, 8), nullable=False),
        sa.Column("previous_close", sa.Numeric(24, 8), nullable=True),
        sa.Column("volume", sa.Numeric(28, 8), nullable=True),
        sa.Column("turnover", sa.Numeric(28, 8), nullable=True),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "open > 0 AND high > 0 AND low > 0 AND close > 0",
            name="ck_stock_daily_bars_prices",
        ),
        sa.CheckConstraint(
            "high >= open AND high >= close AND low <= open AND low <= close",
            name="ck_stock_daily_bars_range",
        ),
        sa.CheckConstraint("volume IS NULL OR volume >= 0", name="ck_stock_daily_bars_volume"),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name="fk_stock_daily_bars_instrument_id_instruments",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stock_daily_bars"),
        sa.UniqueConstraint(
            "instrument_id", "trade_date", name="uq_stock_daily_bars_instrument_date"
        ),
    )
    op.create_index(
        "ix_stock_daily_bars_instrument_date",
        "stock_daily_bars",
        ["instrument_id", "trade_date"],
    )


def _migrate_market_data() -> None:
    """把旧通用价格快照无损迁移到对应的新表。"""
    op.execute(
        """
        INSERT INTO intraday_quotes
          (instrument_id, quote_type, value, change_rate, quoted_at, fetched_at, source)
        SELECT instrument_id, price_type, value, change_rate, as_of_at, fetched_at, source
        FROM instrument_prices
        WHERE price_type IN ('STOCK_LAST', 'FUND_ESTIMATED_NAV')
          AND as_of_at IS NOT NULL
        ON CONFLICT (instrument_id, quote_type, quoted_at, source) DO UPDATE
        SET value = EXCLUDED.value,
            change_rate = EXCLUDED.change_rate,
            fetched_at = EXCLUDED.fetched_at
        """
    )
    op.execute(
        """
        INSERT INTO latest_quotes
          (instrument_id, quote_type, value, change_rate, quoted_at, fetched_at, source)
        SELECT DISTINCT ON (instrument_id, price_type)
          instrument_id, price_type, value, change_rate, as_of_at, fetched_at, source
        FROM instrument_prices
        WHERE price_type IN ('STOCK_LAST', 'FUND_ESTIMATED_NAV')
          AND as_of_at IS NOT NULL
        ORDER BY instrument_id, price_type, as_of_at DESC, fetched_at DESC, id DESC
        """
    )
    op.execute(
        """
        INSERT INTO fund_daily_navs
          (instrument_id, nav_date, unit_nav, daily_return_rate, fetched_at, source)
        SELECT DISTINCT ON (instrument_id, as_of_date)
          instrument_id, as_of_date, value, change_rate, fetched_at, source
        FROM instrument_prices
        WHERE price_type = 'FUND_OFFICIAL_NAV' AND as_of_date IS NOT NULL
        ORDER BY instrument_id, as_of_date, fetched_at DESC, id DESC
        """
    )


def _refactor_positions() -> None:
    """把表单快照转为交易事实，并让持仓表只保留当前投影。"""
    op.add_column(
        "positions",
        sa.Column("realized_profit", sa.Numeric(24, 8), server_default="0", nullable=False),
    )
    op.add_column(
        "positions",
        sa.Column("status", sa.String(length=16), server_default="OPEN", nullable=False),
    )
    op.add_column("positions", sa.Column("first_trade_date", sa.Date(), nullable=True))
    op.add_column("positions", sa.Column("last_trade_date", sa.Date(), nullable=True))
    op.execute(
        """
        UPDATE positions
        SET first_trade_date = input_date,
            last_trade_date = input_date,
            status = CASE WHEN quantity IS NULL THEN 'PENDING' ELSE 'OPEN' END
        """
    )
    op.alter_column("positions", "first_trade_date", nullable=False)
    op.alter_column("positions", "last_trade_date", nullable=False)

    for constraint in (
        "position_input_mode",
        "cost_input_mode",
        "ck_positions_input_quantity",
        "ck_positions_input_total_cost",
        "ck_positions_input_average_cost",
        "ck_positions_input_current_value",
        "ck_positions_quantity",
        "ck_positions_total_cost",
        "ck_positions_average_cost",
        "ck_positions_quantity_average_cost",
        "ck_positions_quantity_estimation",
        "ck_positions_input_shape",
    ):
        op.drop_constraint(constraint, "positions", type_="check")
    op.create_check_constraint(
        "ck_positions_quantity", "positions", "quantity IS NULL OR quantity >= 0"
    )
    op.create_check_constraint("ck_positions_total_cost", "positions", "total_cost >= 0")
    op.create_check_constraint(
        "ck_positions_average_cost",
        "positions",
        "average_cost IS NULL OR average_cost > 0",
    )
    op.create_check_constraint(
        "ck_positions_realized_profit",
        "positions",
        "realized_profit BETWEEN -9999999999999999 AND 9999999999999999",
    )
    op.create_check_constraint(
        "ck_positions_status",
        "positions",
        "status IN ('OPEN', 'CLOSED', 'PENDING')",
    )
    op.create_check_constraint(
        "ck_positions_state",
        "positions",
        "(status = 'PENDING' AND quantity IS NULL AND average_cost IS NULL) OR "
        "(status = 'OPEN' AND quantity > 0 AND average_cost > 0) OR "
        "(status = 'CLOSED' AND quantity = 0 AND total_cost = 0 AND average_cost IS NULL)",
    )

    op.create_table(
        "position_transactions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("position_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_type", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("quantity_change", sa.Numeric(28, 8), nullable=True),
        sa.Column("cash_amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("fee_amount", sa.Numeric(24, 8), server_default="0", nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "transaction_type IN ('OPENING', 'BUY', 'SELL', 'DIVIDEND', 'FEE', "
            "'ADJUSTMENT', 'TRANSFER_IN', 'TRANSFER_OUT')",
            name="ck_position_transactions_type",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'CONFIRMED', 'CANCELLED')",
            name="ck_position_transactions_status",
        ),
        sa.CheckConstraint("fee_amount >= 0", name="ck_position_transactions_fee"),
        sa.ForeignKeyConstraint(
            ["position_id"],
            ["positions.id"],
            name="fk_position_transactions_position_id_positions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_position_transactions"),
    )
    op.create_index(
        "ix_position_transactions_position_date",
        "position_transactions",
        ["position_id", "trade_date", "created_at"],
    )
    op.execute(
        """
        INSERT INTO position_transactions
          (position_id, transaction_type, status, trade_date,
           quantity_change, cash_amount, fee_amount, note, created_at)
        SELECT id, 'OPENING',
          CASE WHEN quantity IS NULL THEN 'PENDING' ELSE 'CONFIRMED' END,
          input_date, quantity, total_cost, 0, '历史持仓迁移', created_at
        FROM positions
        """
    )

    op.create_table(
        "position_daily_snapshots",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("position_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("valuation_type", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Numeric(28, 8), nullable=False),
        sa.Column("unit_price", sa.Numeric(24, 8), nullable=False),
        sa.Column("market_value", sa.Numeric(24, 8), nullable=False),
        sa.Column("total_cost", sa.Numeric(24, 8), nullable=False),
        sa.Column("daily_profit", sa.Numeric(24, 8), nullable=True),
        sa.Column("daily_return_rate", sa.Numeric(12, 8), nullable=True),
        sa.Column("holding_profit", sa.Numeric(24, 8), nullable=False),
        sa.Column("holding_return_rate", sa.Numeric(12, 8), nullable=True),
        sa.Column(
            "calculated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "valuation_type IN ('OFFICIAL', 'ESTIMATED')",
            name="ck_position_daily_snapshots_type",
        ),
        sa.CheckConstraint(
            "quantity >= 0 AND unit_price > 0 AND market_value >= 0 AND total_cost >= 0",
            name="ck_position_daily_snapshots_values",
        ),
        sa.ForeignKeyConstraint(
            ["position_id"],
            ["positions.id"],
            name="fk_position_daily_snapshots_position_id_positions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_position_daily_snapshots"),
        sa.UniqueConstraint(
            "position_id",
            "snapshot_date",
            "valuation_type",
            name="uq_position_daily_snapshots_position_date_type",
        ),
    )
    op.create_index(
        "ix_position_daily_snapshots_position_date",
        "position_daily_snapshots",
        ["position_id", "snapshot_date"],
    )

    for column in (
        "input_mode",
        "cost_input_mode",
        "input_date",
        "input_quantity",
        "input_total_cost",
        "input_average_cost",
        "input_current_value",
        "input_holding_profit",
        "quantity_estimated",
        "quantity_basis_nav",
        "quantity_basis_nav_date",
    ):
        op.drop_column("positions", column)


def _restore_instrument_prices() -> None:
    """按旧契约重建通用价格表并回填现有行情。"""
    op.create_table(
        "instrument_prices",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("price_type", sa.String(length=32), nullable=False),
        sa.Column("value", sa.Numeric(24, 8), nullable=False),
        sa.Column("change_rate", sa.Numeric(12, 8), nullable=True),
        sa.Column("as_of_date", sa.Date(), nullable=True),
        sa.Column("as_of_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "price_type IN ('STOCK_LAST', 'FUND_OFFICIAL_NAV', 'FUND_ESTIMATED_NAV')",
            name="price_type",
        ),
        sa.CheckConstraint("value > 0", name="ck_instrument_prices_positive_value"),
        sa.CheckConstraint(
            "change_rate IS NULL OR change_rate BETWEEN -10 AND 10",
            name="ck_instrument_prices_change_rate",
        ),
        sa.CheckConstraint(
            "as_of_date IS NOT NULL OR as_of_at IS NOT NULL",
            name="ck_instrument_prices_business_time",
        ),
        sa.CheckConstraint(
            "(price_type = 'FUND_OFFICIAL_NAV' AND as_of_date IS NOT NULL "
            "AND as_of_at IS NULL) OR (price_type IN ('STOCK_LAST', "
            "'FUND_ESTIMATED_NAV') AND as_of_date IS NULL AND as_of_at IS NOT NULL)",
            name="ck_instrument_prices_time_semantics",
        ),
        sa.CheckConstraint(
            "char_length(source) BETWEEN 1 AND 80", name="ck_instrument_prices_source"
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name="fk_instrument_prices_instrument_id_instruments",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_instrument_prices"),
    )
    op.create_index(
        "ix_instrument_prices_latest",
        "instrument_prices",
        ["instrument_id", "price_type", "as_of_date", "as_of_at", "fetched_at"],
    )
    op.create_index(
        "uq_instrument_prices_date_source",
        "instrument_prices",
        ["instrument_id", "price_type", "as_of_date", "source"],
        unique=True,
        postgresql_where=sa.text("as_of_date IS NOT NULL"),
    )
    op.create_index(
        "uq_instrument_prices_at_source",
        "instrument_prices",
        ["instrument_id", "price_type", "as_of_at", "source"],
        unique=True,
        postgresql_where=sa.text("as_of_at IS NOT NULL"),
    )
    op.execute(
        """
        INSERT INTO instrument_prices
          (instrument_id, price_type, value, change_rate, as_of_at, fetched_at, source)
        SELECT instrument_id, quote_type, value, change_rate, quoted_at, fetched_at, source
        FROM intraday_quotes
        """
    )
    op.execute(
        """
        INSERT INTO instrument_prices
          (instrument_id, price_type, value, change_rate, as_of_date, fetched_at, source)
        SELECT instrument_id, 'FUND_OFFICIAL_NAV', unit_nav,
          daily_return_rate, nav_date, fetched_at, source
        FROM fund_daily_navs
        """
    )


def _restore_position_inputs() -> None:
    """从当前投影生成兼容的份额录入字段，随后移除新增投影字段。"""
    op.add_column("positions", sa.Column("input_mode", sa.String(24), nullable=True))
    op.add_column("positions", sa.Column("cost_input_mode", sa.String(16), nullable=True))
    op.add_column("positions", sa.Column("input_date", sa.Date(), nullable=True))
    op.add_column("positions", sa.Column("input_quantity", sa.Numeric(28, 8), nullable=True))
    op.add_column("positions", sa.Column("input_total_cost", sa.Numeric(24, 8), nullable=True))
    op.add_column("positions", sa.Column("input_average_cost", sa.Numeric(24, 8), nullable=True))
    op.add_column("positions", sa.Column("input_current_value", sa.Numeric(24, 8), nullable=True))
    op.add_column("positions", sa.Column("input_holding_profit", sa.Numeric(24, 8), nullable=True))
    op.add_column(
        "positions",
        sa.Column(
            "quantity_estimated", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    op.add_column("positions", sa.Column("quantity_basis_nav", sa.Numeric(24, 8), nullable=True))
    op.add_column("positions", sa.Column("quantity_basis_nav_date", sa.Date(), nullable=True))
    op.execute(
        """
        UPDATE positions p
        SET input_mode = CASE
              WHEN i.asset_type = 'STOCK' THEN 'STOCK_SHARES'
              ELSE 'FUND_SHARES'
            END,
            cost_input_mode = 'TOTAL_COST',
            input_date = p.first_trade_date,
            input_quantity = p.quantity,
            input_total_cost = p.total_cost
        FROM instruments i
        WHERE i.id = p.instrument_id
        """
    )
    op.execute("DELETE FROM positions WHERE quantity IS NULL OR quantity = 0")
    for column in ("input_mode", "input_date"):
        op.alter_column("positions", column, nullable=False)
    op.drop_constraint("ck_positions_state", "positions", type_="check")
    op.drop_constraint("ck_positions_status", "positions", type_="check")
    op.drop_constraint("ck_positions_realized_profit", "positions", type_="check")
    op.drop_table("position_transactions")
    op.drop_column("positions", "realized_profit")
    op.drop_column("positions", "status")
    op.drop_column("positions", "first_trade_date")
    op.drop_column("positions", "last_trade_date")
    op.drop_constraint("ck_positions_quantity", "positions", type_="check")
    op.drop_constraint("ck_positions_total_cost", "positions", type_="check")
    op.drop_constraint("ck_positions_average_cost", "positions", type_="check")
    op.create_check_constraint(
        "position_input_mode",
        "positions",
        "input_mode IN ('STOCK_SHARES', 'FUND_AMOUNT', 'FUND_SHARES')",
    )
    op.create_check_constraint(
        "cost_input_mode",
        "positions",
        "cost_input_mode IS NULL OR cost_input_mode IN ('TOTAL_COST', 'AVERAGE_COST')",
    )
    op.create_check_constraint(
        "ck_positions_input_quantity", "positions", "input_quantity IS NULL OR input_quantity > 0"
    )
    op.create_check_constraint(
        "ck_positions_input_total_cost",
        "positions",
        "input_total_cost IS NULL OR input_total_cost > 0",
    )
    op.create_check_constraint(
        "ck_positions_input_average_cost",
        "positions",
        "input_average_cost IS NULL OR input_average_cost > 0",
    )
    op.create_check_constraint(
        "ck_positions_input_current_value",
        "positions",
        "input_current_value IS NULL OR input_current_value > 0",
    )
    op.create_check_constraint(
        "ck_positions_quantity", "positions", "quantity IS NULL OR quantity > 0"
    )
    op.create_check_constraint("ck_positions_total_cost", "positions", "total_cost > 0")
    op.create_check_constraint(
        "ck_positions_average_cost", "positions", "average_cost IS NULL OR average_cost > 0"
    )
    op.create_check_constraint(
        "ck_positions_quantity_average_cost",
        "positions",
        "(quantity IS NULL AND average_cost IS NULL) OR "
        "(quantity IS NOT NULL AND average_cost IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_positions_quantity_estimation",
        "positions",
        "(quantity_estimated IS FALSE AND quantity_basis_nav IS NULL "
        "AND quantity_basis_nav_date IS NULL "
        "AND (input_mode <> 'FUND_AMOUNT' OR quantity IS NULL)) OR "
        "(quantity_estimated IS TRUE AND input_mode = 'FUND_AMOUNT' "
        "AND quantity IS NOT NULL AND quantity_basis_nav > 0 "
        "AND quantity_basis_nav_date IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_positions_input_shape",
        "positions",
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
    )


def _restore_group_table_name() -> None:
    """恢复旧分组表及其约束、索引名称。"""
    op.execute("ALTER INDEX ix_portfolio_groups_user_sort RENAME TO ix_watchlist_groups_user_sort")
    op.execute(
        "ALTER INDEX uq_portfolio_groups_one_default RENAME TO uq_watchlist_groups_one_default"
    )
    renames = (
        (
            "positions",
            "fk_positions_group_id_portfolio_groups",
            "fk_positions_group_id_watchlist_groups",
        ),
        (
            "watchlist_items",
            "fk_watchlist_items_group_id_portfolio_groups",
            "fk_watchlist_items_group_id_watchlist_groups",
        ),
        ("portfolio_groups", "ck_portfolio_groups_version", "ck_watchlist_groups_version"),
        ("portfolio_groups", "ck_portfolio_groups_sort_order", "ck_watchlist_groups_sort_order"),
        ("portfolio_groups", "ck_portfolio_groups_name", "ck_watchlist_groups_name"),
        ("portfolio_groups", "uq_portfolio_groups_user_name", "uq_watchlist_groups_user_name"),
        (
            "portfolio_groups",
            "fk_portfolio_groups_user_id_users",
            "fk_watchlist_groups_user_id_users",
        ),
        ("portfolio_groups", "pk_portfolio_groups", "pk_watchlist_groups"),
    )
    for table, old_name, new_name in renames:
        op.execute(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{old_name}" TO "{new_name}"')
    op.rename_table("portfolio_groups", "watchlist_groups")
