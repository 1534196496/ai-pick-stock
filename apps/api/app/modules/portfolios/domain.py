"""投资账户模块公开的不可变领域记录。"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from app.modules.portfolios.enums import CostInputMode, PositionInputMode


@dataclass(frozen=True, slots=True)
class InvestmentAccountRecord:
    """表示属于当前用户的单个投资账户。"""

    id: UUID
    user_id: UUID
    name: str
    base_currency: str
    sort_order: int
    version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class PositionDraft:
    """承载服务层已校验的原始输入和规范化持仓结果。"""

    account_id: UUID
    instrument_id: UUID
    input_mode: PositionInputMode
    cost_input_mode: CostInputMode | None
    input_date: date
    input_quantity: Decimal | None
    input_total_cost: Decimal | None
    input_average_cost: Decimal | None
    input_current_value: Decimal | None
    input_holding_profit: Decimal | None
    quantity: Decimal | None
    total_cost: Decimal
    average_cost: Decimal | None
    quantity_estimated: bool = False
    quantity_basis_nav: Decimal | None = None
    quantity_basis_nav_date: date | None = None


@dataclass(frozen=True, slots=True)
class PositionRecord:
    """表示属于当前用户且保留完整审计输入的单个持仓。"""

    id: UUID
    account_id: UUID
    instrument_id: UUID
    input_mode: PositionInputMode
    cost_input_mode: CostInputMode | None
    input_date: date
    input_quantity: Decimal | None
    input_total_cost: Decimal | None
    input_average_cost: Decimal | None
    input_current_value: Decimal | None
    input_holding_profit: Decimal | None
    quantity: Decimal | None
    total_cost: Decimal
    average_cost: Decimal | None
    quantity_estimated: bool
    quantity_basis_nav: Decimal | None
    quantity_basis_nav_date: date | None
    version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class PendingFundAmountPosition:
    """表示等待录入日期官方净值补算份额的基金金额持仓。"""

    id: UUID
    instrument_id: UUID
    input_date: date
    current_value: Decimal
    total_cost: Decimal
    version: int
