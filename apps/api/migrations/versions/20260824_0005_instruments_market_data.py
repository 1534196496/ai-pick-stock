"""创建资产主数据、价格快照与同步任务表。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0005"
down_revision: str | None = "20260824_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """建立可扩展资产身份和不混淆价格口径的数据结构。"""
    op.create_table(
        "instruments",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("asset_type", sa.String(length=16), nullable=False),
        sa.Column("market", sa.String(length=16), nullable=False),
        sa.Column("exchange", sa.String(length=16), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("asset_type IN ('STOCK', 'FUND')", name="asset_type"),
        sa.CheckConstraint("market IN ('CN')", name="market"),
        sa.CheckConstraint("exchange IN ('SSE', 'SZSE', 'BSE', 'FUND_CN')", name="exchange"),
        sa.CheckConstraint("currency IN ('CNY')", name="currency"),
        sa.CheckConstraint(
            "ticker = btrim(ticker) AND char_length(ticker) BETWEEN 1 AND 32",
            name="ck_instruments_ticker",
        ),
        sa.CheckConstraint(
            "name = btrim(name) AND char_length(name) BETWEEN 1 AND 160", name="ck_instruments_name"
        ),
        sa.CheckConstraint("char_length(source) BETWEEN 1 AND 80", name="ck_instruments_source"),
        sa.CheckConstraint(
            "(asset_type = 'STOCK' AND exchange IN ('SSE', 'SZSE', 'BSE')) "
            "OR (asset_type = 'FUND' AND exchange = 'FUND_CN')",
            name="ck_instruments_asset_exchange",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_instruments"),
        sa.UniqueConstraint("asset_type", "market", "ticker", name="uq_instruments_identity"),
    )
    op.create_index(
        "ix_instruments_search",
        "instruments",
        ["asset_type", "market", "ticker", "name"],
        unique=False,
    )

    op.create_table(
        "instrument_prices",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("price_type", sa.String(length=32), nullable=False),
        sa.Column("value", sa.Numeric(precision=24, scale=8), nullable=False),
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
            "as_of_date IS NOT NULL OR as_of_at IS NOT NULL",
            name="ck_instrument_prices_business_time",
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
        unique=False,
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

    op.create_table(
        "data_sync_runs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("succeeded_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_summary", sa.String(length=500), nullable=True),
        sa.CheckConstraint(
            "job_type IN ('INSTRUMENT_MASTER', 'STOCK_PRICES', "
            "'FUND_OFFICIAL_NAV', 'FUND_ESTIMATED_NAV')",
            name="sync_job_type",
        ),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED')", name="sync_status"
        ),
        sa.CheckConstraint(
            "succeeded_count >= 0 AND failed_count >= 0", name="ck_data_sync_runs_counts"
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="ck_data_sync_runs_finished_after_start",
        ),
        sa.CheckConstraint(
            "error_summary IS NULL OR char_length(error_summary) <= 500",
            name="ck_data_sync_runs_error_length",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_data_sync_runs"),
    )
    op.create_index(
        "ix_data_sync_runs_job_started", "data_sync_runs", ["job_type", "started_at"], unique=False
    )


def downgrade() -> None:
    """按依赖顺序移除同步任务、价格和资产主数据。"""
    op.drop_index("ix_data_sync_runs_job_started", table_name="data_sync_runs")
    op.drop_table("data_sync_runs")
    op.drop_index("uq_instrument_prices_at_source", table_name="instrument_prices")
    op.drop_index("uq_instrument_prices_date_source", table_name="instrument_prices")
    op.drop_index("ix_instrument_prices_latest", table_name="instrument_prices")
    op.drop_table("instrument_prices")
    op.drop_index("ix_instruments_search", table_name="instruments")
    op.drop_table("instruments")
