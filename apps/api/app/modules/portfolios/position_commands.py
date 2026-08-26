"""持仓服务接收的不可变命令。"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from app.modules.portfolios.enums import CostInputMode


@dataclass(frozen=True, slots=True)
class StockPositionCommand:
    """承载股票数量及二选一成本输入，不包含系统推算字段。"""

    group_id: UUID
    instrument_id: UUID
    input_date: date
    quantity: Decimal
    cost_input_mode: CostInputMode
    total_cost: Decimal | None = None
    average_cost: Decimal | None = None


@dataclass(frozen=True, slots=True)
class UpdateStockPositionCommand:
    """承载股票持仓 PATCH 中出现的可编辑原始输入。"""

    version: int
    group_id: UUID | None = None
    input_date: date | None = None
    quantity: Decimal | None = None
    cost_input_mode: CostInputMode | None = None
    total_cost: Decimal | None = None
    average_cost: Decimal | None = None


@dataclass(frozen=True, slots=True)
class FundNavBasis:
    """表示份额推算使用的基金净值和对应业务日期。"""

    value: Decimal
    nav_date: date


@dataclass(frozen=True, slots=True)
class FundAmountPositionCommand:
    """承载基金快速录入金额、收益和可选净值依据。"""

    group_id: UUID
    instrument_id: UUID
    input_date: date
    current_value: Decimal
    holding_profit: Decimal
    nav_basis: FundNavBasis | None = None


@dataclass(frozen=True, slots=True)
class FundSharesPositionCommand:
    """承载基金份额及总成本或平均成本二选一输入。"""

    group_id: UUID
    instrument_id: UUID
    input_date: date
    quantity: Decimal
    cost_input_mode: CostInputMode
    total_cost: Decimal | None = None
    average_cost: Decimal | None = None


@dataclass(frozen=True, slots=True)
class UpdateFundAmountPositionCommand:
    """承载基金金额模式 PATCH 中出现的原始输入。"""

    version: int
    group_id: UUID | None = None
    input_date: date | None = None
    current_value: Decimal | None = None
    holding_profit: Decimal | None = None


@dataclass(frozen=True, slots=True)
class UpdateFundSharesPositionCommand:
    """承载基金份额模式 PATCH 中出现的原始输入。"""

    version: int
    group_id: UUID | None = None
    input_date: date | None = None
    quantity: Decimal | None = None
    cost_input_mode: CostInputMode | None = None
    total_cost: Decimal | None = None
    average_cost: Decimal | None = None
