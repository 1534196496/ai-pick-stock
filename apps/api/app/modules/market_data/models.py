"""最新行情、分型历史行情与同步任务持久化模型。"""

from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Uuid as SqlUuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, EnumValueType
from app.modules.market_data.enums import PriceType, SyncJobType, SyncStatus


class LatestQuote(Base):
    """保存股票最新价和基金盘中估值的当前读模型。"""

    __tablename__ = "latest_quotes"
    __table_args__ = (
        UniqueConstraint("instrument_id", "quote_type", name="uq_latest_quotes_instrument_type"),
        CheckConstraint(
            "quote_type IN ('STOCK_LAST', 'FUND_ESTIMATED_NAV')",
            name="ck_latest_quotes_type",
        ),
        CheckConstraint("value > 0", name="ck_latest_quotes_value"),
        CheckConstraint(
            "change_rate IS NULL OR change_rate BETWEEN -10 AND 10",
            name="ck_latest_quotes_change_rate",
        ),
        Index("ix_latest_quotes_quoted_at", "quote_type", "quoted_at"),
    )

    id: Mapped[UUID] = mapped_column(
        SqlUuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    instrument_id: Mapped[UUID] = mapped_column(
        SqlUuid, ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False
    )
    quote_type: Mapped[PriceType] = mapped_column(EnumValueType(PriceType, 32), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    change_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    quoted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class IntradayQuote(Base):
    """保存股票价格和基金估值的盘中时间序列。"""

    __tablename__ = "intraday_quotes"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id",
            "quote_type",
            "quoted_at",
            "source",
            name="uq_intraday_quotes_point",
        ),
        CheckConstraint(
            "quote_type IN ('STOCK_LAST', 'FUND_ESTIMATED_NAV')",
            name="ck_intraday_quotes_type",
        ),
        CheckConstraint("value > 0", name="ck_intraday_quotes_value"),
        CheckConstraint(
            "change_rate IS NULL OR change_rate BETWEEN -10 AND 10",
            name="ck_intraday_quotes_change_rate",
        ),
        Index(
            "ix_intraday_quotes_instrument_time",
            "instrument_id",
            "quote_type",
            "quoted_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SqlUuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    instrument_id: Mapped[UUID] = mapped_column(
        SqlUuid, ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False
    )
    quote_type: Mapped[PriceType] = mapped_column(EnumValueType(PriceType, 32), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    change_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    quoted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)


class FundDailyNav(Base):
    """保存基金官方单位净值及其日收益历史。"""

    __tablename__ = "fund_daily_navs"
    __table_args__ = (
        UniqueConstraint("instrument_id", "nav_date", name="uq_fund_daily_navs_instrument_date"),
        CheckConstraint("unit_nav > 0", name="ck_fund_daily_navs_unit_nav"),
        CheckConstraint(
            "accumulated_nav IS NULL OR accumulated_nav > 0",
            name="ck_fund_daily_navs_accumulated_nav",
        ),
        CheckConstraint(
            "daily_return_rate IS NULL OR daily_return_rate BETWEEN -10 AND 10",
            name="ck_fund_daily_navs_return_rate",
        ),
        Index("ix_fund_daily_navs_instrument_date", "instrument_id", "nav_date"),
    )

    id: Mapped[UUID] = mapped_column(
        SqlUuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    instrument_id: Mapped[UUID] = mapped_column(
        SqlUuid, ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False
    )
    nav_date: Mapped[date] = mapped_column(Date, nullable=False)
    unit_nav: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    accumulated_nav: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    daily_return_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class StockDailyBar(Base):
    """保存股票走势图和历史涨跌所需的日线数据。"""

    __tablename__ = "stock_daily_bars"
    __table_args__ = (
        UniqueConstraint("instrument_id", "trade_date", name="uq_stock_daily_bars_instrument_date"),
        CheckConstraint(
            "open > 0 AND high > 0 AND low > 0 AND close > 0",
            name="ck_stock_daily_bars_prices",
        ),
        CheckConstraint(
            "high >= open AND high >= close AND low <= open AND low <= close",
            name="ck_stock_daily_bars_range",
        ),
        CheckConstraint("volume IS NULL OR volume >= 0", name="ck_stock_daily_bars_volume"),
        Index("ix_stock_daily_bars_instrument_date", "instrument_id", "trade_date"),
    )

    id: Mapped[UUID] = mapped_column(
        SqlUuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    instrument_id: Mapped[UUID] = mapped_column(
        SqlUuid, ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False
    )
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    previous_close: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    volume: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    turnover: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class DataSyncRun(Base):
    """记录每次同步的来源、计数、耗时和脱敏错误摘要。"""

    __tablename__ = "data_sync_runs"
    __table_args__ = (
        CheckConstraint(
            "succeeded_count >= 0 AND failed_count >= 0", name="ck_data_sync_runs_counts"
        ),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="ck_data_sync_runs_finished_after_start",
        ),
        CheckConstraint(
            "error_summary IS NULL OR char_length(error_summary) <= 500",
            name="ck_data_sync_runs_error_length",
        ),
        CheckConstraint(
            "job_type IN ('INSTRUMENT_MASTER', 'STOCK_PRICES', "
            "'FUND_OFFICIAL_NAV', 'FUND_ESTIMATED_NAV')",
            name="sync_job_type",
        ),
        CheckConstraint(
            "status IN ('RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED')",
            name="sync_status",
        ),
        Index("ix_data_sync_runs_job_started", "job_type", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(
        SqlUuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    job_type: Mapped[SyncJobType] = mapped_column(EnumValueType(SyncJobType, 32), nullable=False)
    status: Mapped[SyncStatus] = mapped_column(EnumValueType(SyncStatus, 16), nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    succeeded_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    failed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    error_summary: Mapped[str | None] = mapped_column(String(500))


class MarketDataSchedule(Base):
    """保存个人站点唯一一份可热更新行情调度配置。"""

    __tablename__ = "market_data_schedule"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_market_data_schedule_singleton"),
        CheckConstraint(
            "stock_refresh_seconds BETWEEN 15 AND 3600",
            name="ck_market_data_schedule_stock_refresh",
        ),
        CheckConstraint(
            "fund_estimate_refresh_seconds BETWEEN 30 AND 3600",
            name="ck_market_data_schedule_fund_estimate_refresh",
        ),
        CheckConstraint(
            "official_nav_refresh_seconds BETWEEN 120 AND 3600",
            name="ck_market_data_schedule_official_nav_refresh",
        ),
        CheckConstraint("version >= 1", name="ck_market_data_schedule_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1, server_default="1")
    stock_refresh_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, server_default="30"
    )
    fund_estimate_refresh_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60, server_default="60"
    )
    official_nav_refresh_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=300, server_default="300"
    )
    official_nav_window_start: Mapped[time] = mapped_column(
        Time, nullable=False, default=time(16, 0), server_default="16:00:00"
    )
    official_nav_window_end: Mapped[time] = mapped_column(
        Time, nullable=False, default=time(0, 30), server_default="00:30:00"
    )
    instrument_sync_time: Mapped[time] = mapped_column(
        Time, nullable=False, default=time(4, 0), server_default="04:00:00"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
