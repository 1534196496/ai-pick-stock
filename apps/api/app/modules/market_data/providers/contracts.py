"""主数据与行情 Provider 的异步替换契约。"""

from collections.abc import Sequence
from typing import Protocol

from app.modules.market_data.providers.schemas import (
    FundEstimatedNavSnapshot,
    FundOfficialNavSnapshot,
    ProviderInstrument,
    StockPriceSnapshot,
    StockQuoteRequest,
)


class InstrumentMasterProvider(Protocol):
    """提供一期股票和基金主数据。"""

    async def fetch_instruments(self) -> Sequence[ProviderInstrument]:
        """获取已经过边界校验的资产列表。"""
        ...


class StockPriceProvider(Protocol):
    """批量提供用户活跃 A 股最新价格。"""

    async def fetch_stock_prices(
        self, requests: Sequence[StockQuoteRequest]
    ) -> Sequence[StockPriceSnapshot]:
        """按标准代码批量获取股票价格。"""
        ...


class FundNavProvider(Protocol):
    """分别提供官方单位净值与盘中估算净值。"""

    async def fetch_official_navs(
        self,
        tickers: Sequence[str],
    ) -> Sequence[FundOfficialNavSnapshot]:
        """获取带实际净值日期的官方单位净值。"""
        ...

    async def fetch_estimated_navs(
        self,
        tickers: Sequence[str],
    ) -> Sequence[FundEstimatedNavSnapshot]:
        """获取明确标记为估算的盘中净值。"""
        ...
