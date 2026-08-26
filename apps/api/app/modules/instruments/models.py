"""资产主数据持久化模型。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Uuid as SqlUuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, EnumValueType
from app.modules.instruments.enums import AssetType, Currency, Exchange, Market


class Instrument(Base):
    """保存可扩展市场身份、展示名称和来源状态。"""

    __tablename__ = "instruments"
    __table_args__ = (
        UniqueConstraint("asset_type", "market", "ticker", name="uq_instruments_identity"),
        CheckConstraint("asset_type IN ('STOCK', 'FUND')", name="asset_type"),
        CheckConstraint("market IN ('CN')", name="market"),
        CheckConstraint(
            "exchange IN ('SSE', 'SZSE', 'BSE', 'FUND_CN')",
            name="exchange",
        ),
        CheckConstraint("currency IN ('CNY')", name="currency"),
        CheckConstraint(
            "ticker = btrim(ticker) AND char_length(ticker) BETWEEN 1 AND 32",
            name="ck_instruments_ticker",
        ),
        CheckConstraint(
            "name = btrim(name) AND char_length(name) BETWEEN 1 AND 160", name="ck_instruments_name"
        ),
        CheckConstraint("char_length(source) BETWEEN 1 AND 80", name="ck_instruments_source"),
        CheckConstraint(
            "(asset_type = 'STOCK' AND exchange IN ('SSE', 'SZSE', 'BSE')) "
            "OR (asset_type = 'FUND' AND exchange = 'FUND_CN')",
            name="ck_instruments_asset_exchange",
        ),
        Index("ix_instruments_search", "asset_type", "market", "ticker", "name"),
    )

    id: Mapped[UUID] = mapped_column(
        SqlUuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    asset_type: Mapped[AssetType] = mapped_column(EnumValueType(AssetType, 16), nullable=False)
    market: Mapped[Market] = mapped_column(EnumValueType(Market, 16), nullable=False)
    exchange: Mapped[Exchange] = mapped_column(EnumValueType(Exchange, 16), nullable=False)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    currency: Mapped[Currency] = mapped_column(EnumValueType(Currency, 3), nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
