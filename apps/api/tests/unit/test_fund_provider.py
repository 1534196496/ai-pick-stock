"""基金 Provider 主数据、官方净值、回退和估算边界测试。"""

from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest

from app.modules.instruments.enums import AssetType, Exchange
from app.modules.market_data.providers.fund import FundProvider
from app.modules.market_data.providers.http import ProviderHttpClient

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    """Provider 异步测试统一使用 asyncio。"""
    return "asyncio"


async def test_fund_master_classifies_etf_and_lof_as_fund() -> None:
    """基金类型文案不改变统一 FUND 资产身份。"""
    body = (
        'var r = [["510300","HS300ETF","虚构ETF","指数型-股票","XUGOU"],'
        '["160000","XGLOF","虚构LOF","LOF","XUGOU"]];'
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body.encode())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    instruments = await FundProvider(ProviderHttpClient(client=client)).fetch_instruments()
    await client.aclose()
    assert all(item.asset_type is AssetType.FUND for item in instruments)
    assert all(item.exchange is Exchange.FUND_CN for item in instruments)
    assert [item.ticker for item in instruments] == ["510300", "160000"]


async def test_bulk_official_nav_keeps_unit_and_accumulated_values_separate() -> None:
    """批量官方净值保留实际日期，单位净值与累计净值不混用。"""
    body = (
        'var db={datas:[["000001","虚构基金","XG","1.2345","4.5678",'
        '"1.2000","4.5000"]],count:["1"],record:"1",pages:"1",curpage:"1",'
        'showday:["2026-08-21","2026-08-20"]}'
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body.encode())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    snapshots = await FundProvider(ProviderHttpClient(client=client)).fetch_official_navs(
        ["000001"]
    )
    await client.aclose()
    assert snapshots[0].unit_nav == Decimal("1.2345")
    assert snapshots[0].accumulated_nav == Decimal("4.5678")
    assert snapshots[0].nav_date == date(2026, 8, 21)
    assert snapshots[0].source == "eastmoney_fund_official_bulk"


async def test_missing_bulk_nav_uses_single_fund_official_fallback() -> None:
    """批量当前净值为空时，仅对请求标的读取单基金走势最后值。"""
    bulk = (
        'var db={datas:[["000001","虚构基金","XG","","","1.2000","4.5"]],'
        'count:["1"],record:"1",pages:"1",curpage:"1",'
        'showday:["2026-08-24","2026-08-21"]}'
    )
    point_time = int(datetime(2026, 8, 21, tzinfo=UTC).timestamp() * 1000)
    single = f'var Data_netWorthTrend = [{{"x":{point_time},"y":1.2000}}];'
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        content = single if "pingzhongdata" in request.url.path else bulk
        return httpx.Response(200, content=content.encode())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    snapshots = await FundProvider(ProviderHttpClient(client=client)).fetch_official_navs(
        ["000001"]
    )
    await client.aclose()
    assert any("pingzhongdata/000001.js" in path for path in paths)
    assert snapshots[0].unit_nav == Decimal("1.2")
    assert snapshots[0].nav_date == date(2026, 8, 21)
    assert snapshots[0].source == "eastmoney_fund_official_single"


async def test_estimated_nav_is_disabled_by_default_without_http() -> None:
    """默认关闭估算时不产生任何外部请求。"""
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    snapshots = await FundProvider(ProviderHttpClient(client=client)).fetch_estimated_navs(
        ["000001"]
    )
    await client.aclose()
    assert snapshots == []
    assert calls == 0


async def test_enabled_estimate_parses_jsonp_and_converts_china_time() -> None:
    """显式启用后估算值仍保持非权威类型和 UTC 时点。"""
    body = (
        'jsonpgz({"fundcode":"000001","name":"虚构基金","jzrq":"2026-08-21",'
        '"dwjz":"1.20","gsz":"1.2345","gszzl":"2.87",'
        '"gztime":"2026-08-24 14:30"});'
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body.encode())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    snapshots = await FundProvider(
        ProviderHttpClient(client=client),
        estimate_enabled=True,
    ).fetch_estimated_navs(["000001"])
    await client.aclose()
    assert snapshots[0].estimated_nav == Decimal("1.2345")
    assert snapshots[0].as_of_at == datetime(2026, 8, 24, 6, 30, tzinfo=UTC)
    assert snapshots[0].source == "eastmoney_fund_estimate_single"
