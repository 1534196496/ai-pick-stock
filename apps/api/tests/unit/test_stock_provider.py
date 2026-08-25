"""股票 Provider 分页、时间口径、重试和回退测试。"""

from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from app.modules.instruments.enums import Exchange
from app.modules.market_data.providers.http import ProviderHttpClient
from app.modules.market_data.providers.schemas import StockQuoteRequest
from app.modules.market_data.providers.stock import StockProvider

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    """Provider 异步测试统一使用 asyncio。"""
    return "asyncio"


def tencent_quote(ticker: str, value: str, timestamp: str) -> bytes:
    """构造腾讯波浪线行情固定样本。"""
    fields = [""] * 31
    fields[0] = "1"
    fields[1] = "虚构股票"
    fields[2] = ticker
    fields[3] = value
    fields[30] = timestamp
    return f'v_sh{ticker}="{"~".join(fields)}";'.encode("gb18030")


def sina_quote(ticker: str, value: str, day: str, clock: str) -> bytes:
    """构造新浪逗号行情固定样本。"""
    fields = [""] * 32
    fields[0] = "虚构股票"
    fields[3] = value
    fields[30] = day
    fields[31] = clock
    return f'var hq_str_sh{ticker}="{",".join(fields)}";'.encode("gb18030")


async def test_stock_master_paginates_and_maps_exchange_without_ticker_length_rule() -> None:
    """腾讯榜单按 total 分页，并接受非六位 ticker。"""

    def handler(request: httpx.Request) -> httpx.Response:
        offset = request.url.params["offset"]
        rows = (
            [
                {"code": "sh600519", "name": "虚构沪股"},
                {"code": "szLONG-CODE", "name": "未来深股"},
            ]
            if offset == "0"
            else [{"code": "bj920001", "name": "虚构北股"}]
        )
        return httpx.Response(
            200, json={"code": 0, "msg": "ok", "data": {"total": 3, "rank_list": rows}}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = StockProvider(ProviderHttpClient(client=client), page_size=2)
    instruments = await provider.fetch_instruments()
    await client.aclose()
    assert [(item.exchange, item.ticker) for item in instruments] == [
        (Exchange.SSE, "600519"),
        (Exchange.SZSE, "LONG-CODE"),
        (Exchange.BSE, "920001"),
    ]


async def test_tencent_quote_converts_china_local_time_to_utc() -> None:
    """供应商中国本地时间必须转换成 UTC 后进入标准快照。"""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=tencent_quote("600519", "1304.66", "20260824150000"))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = StockProvider(ProviderHttpClient(client=client))
    snapshots = await provider.fetch_stock_prices(
        [StockQuoteRequest(ticker="600519", exchange=Exchange.SSE)]
    )
    await client.aclose()
    assert snapshots[0].value == Decimal("1304.66")
    assert snapshots[0].as_of_at == datetime(2026, 8, 24, 7, 0, tzinfo=UTC)
    assert snapshots[0].source == "tencent_stock_quote"


async def test_tencent_retry_exhaustion_falls_back_to_sina() -> None:
    """腾讯可恢复失败最多尝试三次，然后整批切换新浪。"""
    calls: list[str] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        if request.url.host == "qt.gtimg.cn":
            return httpx.Response(503)
        return httpx.Response(
            200,
            content=sina_quote("600519", "1304.66", "2026-08-24", "15:00:00"),
        )

    async def sleep(delay: float) -> None:
        """记录退避而不真实等待。"""
        sleeps.append(delay)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    http = ProviderHttpClient(client=client, sleep=sleep, jitter=lambda: 0)
    snapshots = await StockProvider(http).fetch_stock_prices(
        [StockQuoteRequest(ticker="600519", exchange=Exchange.SSE)]
    )
    await client.aclose()
    assert calls.count("qt.gtimg.cn") == 3
    assert calls.count("hq.sinajs.cn") == 1
    assert sleeps == [0.5, 1.5]
    assert snapshots[0].source == "sina_stock_quote"
