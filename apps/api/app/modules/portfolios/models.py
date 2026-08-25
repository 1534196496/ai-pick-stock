"""投资账户持久化模型。"""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
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

from app.core.database import Base
from app.modules.portfolios.enums import CostInputMode, PositionInputMode


def position_enum(
    enum_class: type[PositionInputMode | CostInputMode],
    name: str,
) -> Enum:
    """创建以稳定字符串值持久化的持仓枚举映射。"""
    return Enum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=False,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )


class InvestmentAccount(Base):
    """保存用户自定义的投资账户、排序与乐观锁版本。"""

    __tablename__ = "investment_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_investment_accounts_user_name"),
        CheckConstraint(
            "name = btrim(name) AND char_length(name) BETWEEN 1 AND 80",
            name="ck_investment_accounts_name",
        ),
        CheckConstraint("base_currency = 'CNY'", name="ck_investment_accounts_currency"),
        CheckConstraint("sort_order >= 0", name="ck_investment_accounts_sort_order"),
        CheckConstraint("version >= 1", name="ck_investment_accounts_version"),
        Index("ix_investment_accounts_user_sort", "user_id", "sort_order", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        SqlUuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[UUID] = mapped_column(
        SqlUuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    base_currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="CNY", server_default="CNY"
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Position(Base):
    """保存持仓原始输入、规范化结果、推算依据和乐观锁版本。"""

    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("account_id", "instrument_id", name="uq_positions_account_instrument"),
        CheckConstraint("version >= 1", name="ck_positions_version"),
        CheckConstraint(
            "input_quantity IS NULL OR input_quantity > 0",
            name="ck_positions_input_quantity",
        ),
        CheckConstraint(
            "input_total_cost IS NULL OR input_total_cost > 0",
            name="ck_positions_input_total_cost",
        ),
        CheckConstraint(
            "input_average_cost IS NULL OR input_average_cost > 0",
            name="ck_positions_input_average_cost",
        ),
        CheckConstraint(
            "input_current_value IS NULL OR input_current_value > 0",
            name="ck_positions_input_current_value",
        ),
        CheckConstraint("quantity IS NULL OR quantity > 0", name="ck_positions_quantity"),
        CheckConstraint("total_cost > 0", name="ck_positions_total_cost"),
        CheckConstraint(
            "average_cost IS NULL OR average_cost > 0",
            name="ck_positions_average_cost",
        ),
        CheckConstraint(
            "(quantity IS NULL AND average_cost IS NULL) OR "
            "(quantity IS NOT NULL AND average_cost IS NOT NULL)",
            name="ck_positions_quantity_average_cost",
        ),
        CheckConstraint(
            "(quantity_estimated IS FALSE AND quantity_basis_nav IS NULL "
            "AND quantity_basis_nav_date IS NULL "
            "AND (input_mode <> 'FUND_AMOUNT' OR quantity IS NULL)) OR "
            "(quantity_estimated IS TRUE AND input_mode = 'FUND_AMOUNT' "
            "AND quantity IS NOT NULL AND quantity_basis_nav > 0 "
            "AND quantity_basis_nav_date IS NOT NULL)",
            name="ck_positions_quantity_estimation",
        ),
        CheckConstraint(
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
        Index("ix_positions_account_created", "account_id", "created_at", "id"),
        Index("ix_positions_instrument", "instrument_id"),
    )

    id: Mapped[UUID] = mapped_column(
        SqlUuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    account_id: Mapped[UUID] = mapped_column(
        SqlUuid,
        ForeignKey("investment_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    instrument_id: Mapped[UUID] = mapped_column(
        SqlUuid,
        ForeignKey("instruments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    input_mode: Mapped[PositionInputMode] = mapped_column(
        position_enum(PositionInputMode, "position_input_mode"),
        nullable=False,
    )
    cost_input_mode: Mapped[CostInputMode | None] = mapped_column(
        position_enum(CostInputMode, "cost_input_mode")
    )
    input_date: Mapped[date] = mapped_column(Date, nullable=False)
    input_quantity: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    input_total_cost: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    input_average_cost: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    input_current_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    input_holding_profit: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(28, 8))
    total_cost: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    average_cost: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    quantity_estimated: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    quantity_basis_nav: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    quantity_basis_nav_date: Mapped[date | None] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
