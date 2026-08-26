"""资产搜索和详情 API 响应契约。"""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from app.api.schemas import ApiModel
from app.modules.instruments.enums import AssetType, Currency, Exchange, Market
from app.modules.market_data.domain import DataFreshness
from app.modules.market_data.enums import PriceType


class LatestPriceResponse(ApiModel):
    """返回一种明确口径的最新价格及其业务时间和抓取时间。"""

    price_type: PriceType
    value: Decimal
    change_rate: Decimal | None
    as_of_date: date | None
    as_of_at: datetime | None
    fetched_at: datetime
    source: str
    freshness: DataFreshness


class InstrumentResponse(ApiModel):
    """返回一期资产主数据和互不混淆的最新价格列表。"""

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
    latest_prices: list[LatestPriceResponse]


class InstrumentListResponse(ApiModel):
    """返回稳定分页的资产搜索结果。"""

    items: list[InstrumentResponse]
    page: int
    page_size: int
    total: int
