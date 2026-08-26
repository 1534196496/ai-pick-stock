"""持仓模块公开的不可变领域记录。"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from app.modules.portfolios.enums import PositionStatus


@dataclass(frozen=True, slots=True)
class PositionDraft:
    """承载服务层已校验的持仓当前投影。"""

    group_id: UUID
    instrument_id: UUID
    trade_date: date
    quantity: Decimal
    total_cost: Decimal
    average_cost: Decimal


@dataclass(frozen=True, slots=True)
class PositionRecord:
    """表示属于当前用户的精简持仓当前投影。"""

    id: UUID
    group_id: UUID
    instrument_id: UUID
    quantity: Decimal | None
    total_cost: Decimal
    average_cost: Decimal | None
    realized_profit: Decimal
    status: PositionStatus
    first_trade_date: date
    last_trade_date: date
    version: int
    created_at: datetime
    updated_at: datetime
