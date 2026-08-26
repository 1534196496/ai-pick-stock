"""精简持仓投影、交易事实和每日收益快照模型。"""

from datetime import date, datetime
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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Uuid as SqlUuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, EnumValueType
from app.modules.portfolios.enums import PositionStatus, TransactionStatus, TransactionType


class Position(Base):
    """保存由交易事实汇总得到的当前持仓投影。"""

    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("group_id", "instrument_id", name="uq_positions_group_instrument"),
        CheckConstraint("version >= 1", name="ck_positions_version"),
        CheckConstraint("quantity IS NULL OR quantity >= 0", name="ck_positions_quantity"),
        CheckConstraint("total_cost >= 0", name="ck_positions_total_cost"),
        CheckConstraint(
            "average_cost IS NULL OR average_cost > 0",
            name="ck_positions_average_cost",
        ),
        CheckConstraint(
            "realized_profit BETWEEN -9999999999999999 AND 9999999999999999",
            name="ck_positions_realized_profit",
        ),
        CheckConstraint(
            "status IN ('OPEN', 'CLOSED', 'PENDING')",
            name="ck_positions_status",
        ),
        CheckConstraint(
            "(status = 'PENDING' AND quantity IS NULL AND average_cost IS NULL) OR "
            "(status = 'OPEN' AND quantity > 0 AND average_cost > 0) OR "
            "(status = 'CLOSED' AND quantity = 0 AND total_cost = 0 "
            "AND average_cost IS NULL)",
            name="ck_positions_state",
        ),
        Index("ix_positions_group_created", "group_id", "created_at", "id"),
        Index("ix_positions_instrument", "instrument_id"),
    )

    id: Mapped[UUID] = mapped_column(
        SqlUuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    group_id: Mapped[UUID] = mapped_column(
        SqlUuid,
        ForeignKey("portfolio_groups.id", ondelete="RESTRICT"),
        nullable=False,
    )
    instrument_id: Mapped[UUID] = mapped_column(
        SqlUuid,
        ForeignKey("instruments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    total_cost: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    average_cost: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    realized_profit: Mapped[Decimal] = mapped_column(
        Numeric(24, 8), nullable=False, default=Decimal("0"), server_default="0"
    )
    status: Mapped[PositionStatus] = mapped_column(
        EnumValueType(PositionStatus, 16),
        nullable=False,
        default=PositionStatus.OPEN,
        server_default=PositionStatus.OPEN.value,
    )
    first_trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PositionTransaction(Base):
    """保存可重放的持仓数量和成本变化事实。"""

    __tablename__ = "position_transactions"
    __table_args__ = (
        CheckConstraint(
            "transaction_type IN ('OPENING', 'BUY', 'SELL', 'DIVIDEND', 'FEE', "
            "'ADJUSTMENT', 'TRANSFER_IN', 'TRANSFER_OUT')",
            name="ck_position_transactions_type",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'CONFIRMED', 'CANCELLED')",
            name="ck_position_transactions_status",
        ),
        CheckConstraint("fee_amount >= 0", name="ck_position_transactions_fee"),
        Index(
            "ix_position_transactions_position_date",
            "position_id",
            "trade_date",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SqlUuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    position_id: Mapped[UUID] = mapped_column(
        SqlUuid,
        ForeignKey("positions.id", ondelete="CASCADE"),
        nullable=False,
    )
    transaction_type: Mapped[TransactionType] = mapped_column(
        EnumValueType(TransactionType, 24), nullable=False
    )
    status: Mapped[TransactionStatus] = mapped_column(
        EnumValueType(TransactionStatus, 16), nullable=False
    )
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity_change: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    cash_amount: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    fee_amount: Mapped[Decimal] = mapped_column(
        Numeric(24, 8), nullable=False, default=Decimal("0"), server_default="0"
    )
    note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PositionDailySnapshot(Base):
    """保存每日收益曲线所需的最终或估算持仓快照。"""

    __tablename__ = "position_daily_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "position_id",
            "snapshot_date",
            "valuation_type",
            name="uq_position_daily_snapshots_position_date_type",
        ),
        CheckConstraint(
            "quantity >= 0 AND unit_price > 0 AND market_value >= 0 AND total_cost >= 0",
            name="ck_position_daily_snapshots_values",
        ),
        CheckConstraint(
            "valuation_type IN ('OFFICIAL', 'ESTIMATED')",
            name="ck_position_daily_snapshots_type",
        ),
        Index(
            "ix_position_daily_snapshots_position_date",
            "position_id",
            "snapshot_date",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SqlUuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    position_id: Mapped[UUID] = mapped_column(
        SqlUuid,
        ForeignKey("positions.id", ondelete="CASCADE"),
        nullable=False,
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    valuation_type: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    market_value: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    daily_profit: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    daily_return_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    holding_profit: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    holding_return_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
