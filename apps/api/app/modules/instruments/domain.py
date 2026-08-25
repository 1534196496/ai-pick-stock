"""资产模块对服务层公开的不可变记录。"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.instruments.enums import AssetType, Currency, Exchange, Market


@dataclass(frozen=True, slots=True)
class InstrumentRecord:
    """表示一期可搜索和引用的单个资产。"""

    id: UUID
    asset_type: AssetType
    market: Market
    exchange: Exchange
    ticker: str
    name: str
    currency: Currency
    source: str
    source_updated_at: datetime | None
    updated_at: datetime
