"""天天基金主数据、官方净值与可选估算净值适配器。"""

import asyncio
import json
import re
import time
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.modules.instruments.enums import AssetType, Currency, Exchange, Market
from app.modules.market_data.providers.http import (
    ProviderHttpClient,
    ProviderPayloadError,
)
from app.modules.market_data.providers.schemas import (
    FundEstimatedNavSnapshot,
    FundOfficialNavSnapshot,
    ProviderInstrument,
)

_FUND_MASTER_URL = "https://fund.eastmoney.com/js/fundcode_search.js"
_FUND_OFFICIAL_BULK_URL = "https://fund.eastmoney.com/Data/Fund_JJJZ_Data.aspx"
_FUND_OFFICIAL_SINGLE = "https://fund.eastmoney.com/pingzhongdata/{ticker}.js"
_FUND_ESTIMATE_SINGLE = "https://fundgz.1234567.com.cn/js/{ticker}.js"
_HEADERS = {
    "User-Agent": "ai-pick-stock-worker/2.0",
    "Referer": "https://fund.eastmoney.com/",
}


class FundProvider:
    """同步基金主数据和官方净值，并可选读取非权威估算值。"""

    def __init__(
        self,
        http: ProviderHttpClient,
        *,
        estimate_enabled: bool = False,
        fallback_concurrency: int = 2,
    ) -> None:
        """注入共享 HTTP，并限制单基金回退并发。"""
        self._http = http
        self._estimate_enabled = estimate_enabled
        self._semaphore = asyncio.Semaphore(fallback_concurrency)

    async def fetch_instruments(self) -> list[ProviderInstrument]:
        """读取基金代码脚本并把 ETF、LOF 等统一归为 FUND。"""
        response = await self._http.get(_FUND_MASTER_URL, headers=_HEADERS, encoding="utf-8-sig")
        text = response.text().strip()
        try:
            rows = json.loads(text.removeprefix("var r = ").removesuffix(";"))
        except json.JSONDecodeError as error:
            raise ProviderPayloadError("基金主数据脚本不是有效 JSON 数组") from error
        if not isinstance(rows, list):
            raise ProviderPayloadError("基金主数据根节点不是列表")
        instruments: list[ProviderInstrument] = []
        for raw in rows:
            if not isinstance(raw, list) or len(raw) != 5:
                raise ProviderPayloadError("基金主数据行字段数量异常")
            ticker, _, name, _, _ = raw
            if not isinstance(ticker, str) or not isinstance(name, str):
                raise ProviderPayloadError("基金主数据代码或名称类型异常")
            instruments.append(
                ProviderInstrument(
                    asset_type=AssetType.FUND,
                    market=Market.CN,
                    exchange=Exchange.FUND_CN,
                    ticker=ticker,
                    name=name.strip(),
                    currency=Currency.CNY,
                    source="eastmoney_fund_master",
                    source_updated_at=datetime.now(UTC),
                )
            )
        return instruments

    async def fetch_official_navs(
        self,
        tickers: list[str],
    ) -> list[FundOfficialNavSnapshot]:
        """批量读取官方单位净值，缺失标的再限量读取单基金脚本。"""
        requested = set(tickers)
        response = await self._http.get(
            _FUND_OFFICIAL_BULK_URL,
            params={
                "t": "1",
                "lx": "1",
                "letter": "",
                "gsid": "",
                "text": "",
                "sort": "zdf,desc",
                "page": "1,50000",
                "dt": str(int(time.time() * 1000)),
                "atfc": "",
                "onlySale": "0",
            },
            headers=_HEADERS,
            encoding="utf-8-sig",
        )
        snapshots = _parse_official_bulk(response.text(), requested=requested)
        found = {snapshot.ticker for snapshot in snapshots}
        missing = sorted(requested - found)
        if missing:
            fallback = await asyncio.gather(
                *(self._fetch_official_single(ticker) for ticker in missing),
                return_exceptions=True,
            )
            snapshots.extend(item for item in fallback if isinstance(item, FundOfficialNavSnapshot))
        return snapshots

    async def fetch_estimated_navs(
        self,
        tickers: list[str],
    ) -> list[FundEstimatedNavSnapshot]:
        """默认返回空；显式启用后只读取结构化 JSONP 且失败不伪造。"""
        if not self._estimate_enabled or not tickers:
            return []
        results = await asyncio.gather(
            *(self._fetch_estimated_single(ticker) for ticker in tickers),
            return_exceptions=True,
        )
        return [item for item in results if isinstance(item, FundEstimatedNavSnapshot)]

    async def _fetch_official_single(self, ticker: str) -> FundOfficialNavSnapshot:
        """从单基金走势中取最后一条官方单位净值和真实日期。"""
        async with self._semaphore:
            response = await self._http.get(
                _FUND_OFFICIAL_SINGLE.format(ticker=ticker),
                params={"v": str(int(time.time()))},
                headers={**_HEADERS, "Referer": f"https://fund.eastmoney.com/{ticker}.html"},
                encoding="utf-8-sig",
            )
        match = re.search(r"Data_netWorthTrend\s*=\s*(\[.*?\]);", response.text())
        if match is None:
            raise ProviderPayloadError("单基金官方净值字段缺失")
        try:
            rows = json.loads(match.group(1))
            last = rows[-1]
            business_date = datetime.fromtimestamp(int(last["x"]) / 1000, tz=UTC).date()
            return FundOfficialNavSnapshot.model_validate(
                {
                    "ticker": ticker,
                    "unit_nav": str(last["y"]),
                    "accumulated_nav": None,
                    "nav_date": business_date,
                    "fetched_at": datetime.now(UTC),
                    "source": "eastmoney_fund_official_single",
                }
            )
        except (
            json.JSONDecodeError,
            IndexError,
            KeyError,
            TypeError,
            ValueError,
            ValidationError,
        ) as error:
            raise ProviderPayloadError("单基金官方净值结构异常") from error

    async def _fetch_estimated_single(self, ticker: str) -> FundEstimatedNavSnapshot:
        """解析可选 JSONP 估算值，明确保留估算业务时点。"""
        async with self._semaphore:
            response = await self._http.get(
                _FUND_ESTIMATE_SINGLE.format(ticker=ticker),
                params={"rt": str(int(time.time() * 1000))},
                headers=_HEADERS,
                encoding="utf-8-sig",
            )
        match = re.fullmatch(r"jsonpgz\((\{.*\})\);?\s*", response.text().strip())
        if match is None:
            raise ProviderPayloadError("基金估算 JSONP 包装异常")
        try:
            payload: dict[str, Any] = json.loads(match.group(1))
            if payload.get("fundcode") != ticker:
                raise ProviderPayloadError("基金估算代码不匹配")
            as_of = (
                datetime.strptime(
                    str(payload["gztime"]),
                    "%Y-%m-%d %H:%M",
                )
                .replace(tzinfo=ZoneInfo("Asia/Shanghai"))
                .astimezone(UTC)
            )
            return FundEstimatedNavSnapshot.model_validate(
                {
                    "ticker": ticker,
                    "estimated_nav": payload["gsz"],
                    "as_of_at": as_of,
                    "fetched_at": datetime.now(UTC),
                    "source": "eastmoney_fund_estimate_single",
                }
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, ValidationError) as error:
            raise ProviderPayloadError("基金估算字段校验失败") from error


def _parse_official_bulk(
    text: str,
    *,
    requested: set[str],
) -> list[FundOfficialNavSnapshot]:
    """从批量页面只提取 datas 和 showday，避免执行第三方 JavaScript。"""
    data_match = re.search(r"datas:(\[.*?\]),count:", text)
    day_match = re.search(r"showday:(\[[^]]+\])", text)
    if data_match is None or day_match is None:
        raise ProviderPayloadError("基金官方净值批量结构异常")
    try:
        rows = json.loads(data_match.group(1))
        days = json.loads(day_match.group(1))
        nav_date = date.fromisoformat(days[0])
    except (json.JSONDecodeError, IndexError, TypeError, ValueError) as error:
        raise ProviderPayloadError("基金官方净值日期异常") from error
    snapshots: list[FundOfficialNavSnapshot] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 7:
            raise ProviderPayloadError("基金官方净值行字段数量异常")
        ticker = row[0]
        if not isinstance(ticker, str) or (requested and ticker not in requested):
            continue
        unit_nav = row[3]
        if unit_nav in {None, ""}:
            continue
        try:
            snapshots.append(
                FundOfficialNavSnapshot.model_validate(
                    {
                        "ticker": ticker,
                        "unit_nav": unit_nav,
                        "accumulated_nav": row[4] or None,
                        "nav_date": nav_date,
                        "fetched_at": datetime.now(UTC),
                        "source": "eastmoney_fund_official_bulk",
                    }
                )
            )
        except ValidationError as error:
            raise ProviderPayloadError("基金官方净值字段校验失败") from error
    return snapshots
