"""资产主数据持久化模型。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Uuid as SqlUuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.modules.instruments.enums import AssetType, Currency, Exchange, Market


def enum_type(enum_class: type[AssetType | Market | Exchange | Currency], name: str) -> Enum:
    """创建以字符串值存储且由数据库检查约束保护的枚举类型。"""
    return Enum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=False,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )


class Instrument(Base):
    """保存可扩展市场身份、展示名称和来源状态。"""

    __tablename__ = "instruments"
    __table_args__ = (
        UniqueConstraint("asset_type", "market", "ticker", name="uq_instruments_identity"),
        CheckConstraint(
            "ticker = btrim(ticker) AND char_length(ticker) BETWEEN 1 AND 32",
            name="ck_instruments_ticker",
        ),
        CheckConstraint(
            "name = btrim(name) AND char_length(name) BETWEEN 1 AND 160", name="ck_instruments_name"
        ),
        CheckConstraint("char_length(source) BETWEEN 1 AND 80", name="ck_instruments_source"),
        Index("ix_instruments_search", "asset_type", "market", "ticker", "name"),
    )

    id: Mapped[UUID] = mapped_column(
        SqlUuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    asset_type: Mapped[AssetType] = mapped_column(
        enum_type(AssetType, "asset_type"), nullable=False
    )
    market: Mapped[Market] = mapped_column(enum_type(Market, "market"), nullable=False)
    exchange: Mapped[Exchange] = mapped_column(enum_type(Exchange, "exchange"), nullable=False)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    currency: Mapped[Currency] = mapped_column(enum_type(Currency, "currency"), nullable=False)
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
