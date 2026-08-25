"""资产搜索、详情与最新行情组合用例。"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.modules.instruments.domain import InstrumentRecord
from app.modules.instruments.enums import AssetType
from app.modules.instruments.repository import InstrumentRepository
from app.modules.market_data.domain import DataFreshness, PriceRecord
from app.modules.market_data.enums import PriceType
from app.modules.market_data.repository import MarketDataRepository
from app.modules.market_data.service import MarketDataFreshnessPolicy

_PRICE_ORDER = {
    PriceType.STOCK_LAST: 0,
    PriceType.FUND_OFFICIAL_NAV: 1,
    PriceType.FUND_ESTIMATED_NAV: 2,
}


class InstrumentError(Exception):
    """表示可安全映射为公开接口错误的资产领域问题。"""

    def __init__(self, *, code: str, message: str) -> None:
        """保存稳定错误码和用户可理解的提示。"""
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class PriceView:
    """组合最新价格快照和读取时计算的新鲜度。"""

    record: PriceRecord
    freshness: DataFreshness


@dataclass(frozen=True, slots=True)
class InstrumentView:
    """组合资产主数据和互不混淆的最新价格列表。"""

    record: InstrumentRecord
    prices: tuple[PriceView, ...]


class InstrumentService:
    """提供只读取本地数据库的资产搜索和详情。"""

    def __init__(
        self,
        instrument_repository: InstrumentRepository,
        market_data_repository: MarketDataRepository,
        freshness_policy: MarketDataFreshnessPolicy,
    ) -> None:
        """注入资产、行情读取边界和统一新鲜度规则。"""
        self._instrument_repository = instrument_repository
        self._market_data_repository = market_data_repository
        self._freshness_policy = freshness_policy

    async def search(
        self,
        *,
        query: str | None,
        asset_type: AssetType | None,
        page: int,
        page_size: int,
    ) -> tuple[list[InstrumentView], int]:
        """规范化搜索词并分页组合每个资产的最新价格。"""
        normalized_query = query.strip() if query is not None else None
        if not normalized_query:
            normalized_query = None
        records, total = await self._instrument_repository.search_active(
            query=normalized_query,
            asset_type=asset_type,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return await self._views(records), total

    async def get(self, *, instrument_id: UUID) -> InstrumentView:
        """读取单个一期资产，不存在或已停用时返回统一领域错误。"""
        record = await self._instrument_repository.get_active(instrument_id=instrument_id)
        if record is None:
            raise InstrumentError(code="INSTRUMENT_NOT_FOUND", message="资产不存在")
        return (await self._views([record]))[0]

    async def _views(self, records: list[InstrumentRecord]) -> list[InstrumentView]:
        """批量读取价格以避免资产列表产生逐行查询。"""
        price_map = await self._market_data_repository.latest_prices(
            instrument_ids=[record.id for record in records]
        )
        now = datetime.now(UTC)
        return [
            InstrumentView(
                record=record,
                prices=tuple(
                    PriceView(
                        record=price,
                        freshness=self._freshness_policy.for_price(price, now=now),
                    )
                    for price in sorted(
                        price_map.get(record.id, []),
                        key=lambda item: _PRICE_ORDER[item.price_type],
                    )
                ),
            )
            for record in records
        ]
