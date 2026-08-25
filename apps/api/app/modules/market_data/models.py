"""价格快照与同步任务持久化模型。"""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy import Uuid as SqlUuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.modules.market_data.enums import PriceType, SyncJobType, SyncStatus


def enum_type(enum_class: type[PriceType | SyncJobType | SyncStatus], name: str) -> Enum:
    """创建稳定字符串枚举映射。"""
    return Enum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=False,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )


class InstrumentPrice(Base):
    """保存不混淆口径、业务时间和抓取时间的价格快照。"""

    __tablename__ = "instrument_prices"
    __table_args__ = (
        CheckConstraint("value > 0", name="ck_instrument_prices_positive_value"),
        CheckConstraint(
            "as_of_date IS NOT NULL OR as_of_at IS NOT NULL",
            name="ck_instrument_prices_business_time",
        ),
        CheckConstraint("char_length(source) BETWEEN 1 AND 80", name="ck_instrument_prices_source"),
        Index(
            "ix_instrument_prices_latest",
            "instrument_id",
            "price_type",
            "as_of_date",
            "as_of_at",
            "fetched_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SqlUuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    instrument_id: Mapped[UUID] = mapped_column(
        SqlUuid, ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False
    )
    price_type: Mapped[PriceType] = mapped_column(
        enum_type(PriceType, "price_type"), nullable=False
    )
    value: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    as_of_date: Mapped[date | None] = mapped_column(Date)
    as_of_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
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
        Index("ix_data_sync_runs_job_started", "job_type", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(
        SqlUuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    job_type: Mapped[SyncJobType] = mapped_column(
        enum_type(SyncJobType, "sync_job_type"), nullable=False
    )
    status: Mapped[SyncStatus] = mapped_column(enum_type(SyncStatus, "sync_status"), nullable=False)
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
