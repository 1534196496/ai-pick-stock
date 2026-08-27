"""天天基金主数据、官方净值与可选估算净值适配器。"""

import asyncio
import json
import re
import time
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.modules.instruments.enums import AssetType, Currency, Exchange, Market
from app.modules.market_data.providers.http import (
    ProviderHttpClient,
    ProviderPayloadError,
    ProviderUnavailableError,
)
from app.modules.market_data.providers.schemas import (
    FundEstimatedNavSnapshot,
    FundOfficialNavSnapshot,
    ProviderInstrument,
)

_FUND_MASTER_URL = "https://fund.eastmoney.com/js/fundcode_search.js"
_FUND_OFFICIAL_BULK_URL = "https://fund.eastmoney.com/Data/Fund_JJJZ_Data.aspx"
_FUND_OFFICIAL_HISTORY_URL = "https://api.fund.eastmoney.com/f10/lsjz"
_FUND_OFFICIAL_HISTORY_FALLBACK_URL = (
    "https://stock.finance.sina.com.cn/fundInfo/api/openapi.php/CaihuiFundInfoService.getNav"
)
_FUND_ESTIMATE_BULK_URL = "https://fundcomapi.tiantianfunds.com/mm/newCore/FundValuationLast"
_FUND_ESTIMATE_FALLBACK_URL = "https://fund.dayfund.com.cn/ajs/ajaxdata.shtml"
_FUND_ESTIMATE_BATCH_SIZE = 100
_SHANGHAI_TIMEZONE = ZoneInfo("Asia/Shanghai")
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
        """批量读取官方单位净值，缺失标的再限量读取最新历史净值。"""
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
        """显式启用后优先读取东方财富估算，缺失标的再读取季报模型估值。"""
        if not self._estimate_enabled or not tickers:
            return []
        unique_tickers = list(dict.fromkeys(tickers))
        results = await asyncio.gather(
            *(
                self._fetch_estimated_batch(
                    unique_tickers[offset : offset + _FUND_ESTIMATE_BATCH_SIZE]
                )
                for offset in range(0, len(unique_tickers), _FUND_ESTIMATE_BATCH_SIZE)
            ),
            return_exceptions=True,
        )
        snapshots = [
            snapshot for result in results if isinstance(result, list) for snapshot in result
        ]
        found = {snapshot.ticker for snapshot in snapshots}
        missing = [ticker for ticker in unique_tickers if ticker not in found]
        if missing:
            fallback = await asyncio.gather(
                *(self._fetch_estimated_fallback(ticker) for ticker in missing),
                return_exceptions=True,
            )
            snapshots.extend(
                item for item in fallback if isinstance(item, FundEstimatedNavSnapshot)
            )
        return snapshots

    async def fetch_official_nav_history(
        self,
        ticker: str,
        *,
        limit: int = 250,
    ) -> list[FundOfficialNavSnapshot]:
        """读取单只基金最近官方净值历史，供走势和 AI 分析复用。"""
        if not 20 <= limit <= 500:
            raise ValueError("基金历史条数必须在 20 到 500 之间")
        page_size = 20
        page_count = (limit + page_size - 1) // page_size
        pages = await asyncio.gather(
            *(
                self._fetch_official_nav_history_page(
                    ticker,
                    page_index=page_index,
                    page_size=page_size,
                )
                for page_index in range(1, page_count + 1)
            )
        )
        snapshots_by_date = {snapshot.nav_date: snapshot for page in pages for snapshot in page}
        return sorted(snapshots_by_date.values(), key=lambda item: item.nav_date)[-limit:]

    async def _fetch_official_nav_history_page(
        self,
        ticker: str,
        *,
        page_index: int,
        page_size: int,
    ) -> list[FundOfficialNavSnapshot]:
        """在共享并发限制内读取并解析一页官方基金净值。"""
        async with self._semaphore:
            response = await self._http.get(
                _FUND_OFFICIAL_HISTORY_URL,
                params={
                    "fundCode": ticker,
                    "pageIndex": str(page_index),
                    "pageSize": str(page_size),
                },
                headers={
                    **_HEADERS,
                    "Referer": f"https://fundf10.eastmoney.com/{ticker}.html",
                },
                encoding="utf-8-sig",
            )
        return _parse_eastmoney_official_history_list(
            response.text(),
            ticker=ticker,
            fetched_at=datetime.now(UTC),
        )

    async def _fetch_official_single(self, ticker: str) -> FundOfficialNavSnapshot:
        """优先读取东方财富历史净值，响应异常时回退新浪历史净值。"""
        async with self._semaphore:
            try:
                response = await self._http.get(
                    _FUND_OFFICIAL_HISTORY_URL,
                    params={
                        "fundCode": ticker,
                        "pageIndex": "1",
                        "pageSize": "2",
                    },
                    headers={
                        **_HEADERS,
                        "Referer": f"https://fundf10.eastmoney.com/{ticker}.html",
                    },
                    encoding="utf-8-sig",
                )
                return _parse_eastmoney_official_history(
                    response.text(),
                    ticker=ticker,
                    fetched_at=datetime.now(UTC),
                )
            except (ProviderUnavailableError, ProviderPayloadError):
                response = await self._http.get(
                    _FUND_OFFICIAL_HISTORY_FALLBACK_URL,
                    params={
                        "symbol": ticker,
                        "datefrom": "",
                        "dateto": "",
                        "page": "1",
                        "num": "2",
                    },
                    headers={"User-Agent": _HEADERS["User-Agent"]},
                    encoding="utf-8-sig",
                )
                return _parse_sina_official_history(
                    response.text(),
                    ticker=ticker,
                    fetched_at=datetime.now(UTC),
                )

    async def _fetch_estimated_batch(
        self,
        tickers: list[str],
    ) -> list[FundEstimatedNavSnapshot]:
        """批量读取新版估值接口，并把百分数统一转换为比值。"""
        response = await self._http.get(
            _FUND_ESTIMATE_BULK_URL,
            params={
                "FCODES": ",".join(tickers),
                "FIELDS": "FCODE,SHORTNAME,GSZZL,GZTIME,GSZ,NAV,PDATE",
            },
            headers={**_HEADERS, "Referer": "https://fund.eastmoney.com/"},
            encoding="utf-8-sig",
        )
        try:
            payload = json.loads(response.text(), parse_float=Decimal)
        except json.JSONDecodeError as error:
            raise ProviderPayloadError("基金估算响应不是有效 JSON") from error
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise ProviderPayloadError("基金估算响应状态异常")
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise ProviderPayloadError("基金估算数据不是列表")
        requested = set(tickers)
        snapshots: list[FundEstimatedNavSnapshot] = []
        for row in rows:
            if not isinstance(row, dict):
                raise ProviderPayloadError("基金估算行不是对象")
            ticker = row.get("FCODE")
            estimated_nav = row.get("GSZ")
            percentage = row.get("GSZZL")
            base_nav = row.get("NAV")
            quote_time = row.get("GZTIME")
            if not isinstance(ticker, str) or ticker not in requested:
                continue
            if estimated_nav in {None, ""} or percentage in {None, ""} or not quote_time:
                continue
            try:
                as_of = (
                    datetime.strptime(str(quote_time), "%Y-%m-%d %H:%M")
                    .replace(tzinfo=_SHANGHAI_TIMEZONE)
                    .astimezone(UTC)
                )
                snapshots.append(
                    FundEstimatedNavSnapshot.model_validate(
                        {
                            "ticker": ticker,
                            "estimated_nav": estimated_nav,
                            "change_rate": (
                                _relative_change(estimated_nav, base_nav)
                                if base_nav not in {None, ""}
                                else _percentage_ratio(percentage)
                            ),
                            "as_of_at": as_of,
                            "fetched_at": datetime.now(UTC),
                            "source": "eastmoney_fund_estimate_bulk",
                        }
                    )
                )
            except (ValueError, ValidationError) as error:
                raise ProviderPayloadError("基金估算字段校验失败") from error
        return snapshots

    async def _fetch_estimated_fallback(self, ticker: str) -> FundEstimatedNavSnapshot:
        """读取基于最新季报重仓股建模的单基金估值，作为 QDII 等缺值标的回退。"""
        async with self._semaphore:
            response = await self._http.get(
                _FUND_ESTIMATE_FALLBACK_URL,
                params={"showtype": "getfundvalue", "fundcode": ticker},
                headers={
                    "User-Agent": _HEADERS["User-Agent"],
                    "Referer": f"https://fund.dayfund.com.cn/fundpre/{ticker}.html",
                },
                encoding="utf-8-sig",
            )
        return _parse_estimated_fallback(
            response.text(),
            ticker=ticker,
            fetched_at=datetime.now(UTC),
        )


def _parse_eastmoney_official_history(
    text: str,
    *,
    ticker: str,
    fetched_at: datetime,
) -> FundOfficialNavSnapshot:
    """解析东方财富 F10 最新两条净值，并用相邻净值计算精确涨跌率。"""
    try:
        payload = json.loads(text, parse_float=Decimal)
        rows = payload["Data"]["LSJZList"]
        current = rows[0]
        previous_nav = rows[1]["DWJZ"] if len(rows) >= 2 else None
        return FundOfficialNavSnapshot.model_validate(
            {
                "ticker": ticker,
                "unit_nav": current["DWJZ"],
                "accumulated_nav": current.get("LJJZ") or None,
                "change_rate": (
                    _relative_change(current["DWJZ"], previous_nav)
                    if previous_nav not in {None, ""}
                    else _optional_percentage_ratio(current.get("JZZZL"))
                ),
                "nav_date": date.fromisoformat(current["FSRQ"]),
                "fetched_at": fetched_at,
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
        raise ProviderPayloadError("东方财富单基金官方净值结构异常") from error


def _parse_eastmoney_official_history_list(
    text: str,
    *,
    ticker: str,
    fetched_at: datetime,
) -> list[FundOfficialNavSnapshot]:
    """把东方财富净值历史转换为按日期升序的严格快照列表。"""
    try:
        payload = json.loads(text, parse_float=Decimal)
        if payload.get("ErrCode") != 0:
            raise ValueError("东方财富基金历史响应状态异常")
        rows = payload["Data"]["LSJZList"]
        snapshots = [
            FundOfficialNavSnapshot.model_validate(
                {
                    "ticker": ticker,
                    "unit_nav": row["DWJZ"],
                    "accumulated_nav": row.get("LJJZ") or None,
                    "change_rate": _optional_percentage_ratio(row.get("JZZZL")),
                    "nav_date": row["FSRQ"],
                    "fetched_at": fetched_at,
                    "source": "eastmoney_fund_official_history",
                }
            )
            for row in rows
            if isinstance(row, dict) and row.get("DWJZ") not in {None, ""}
        ]
        if not snapshots:
            raise ValueError("东方财富基金历史为空")
        return sorted(snapshots, key=lambda item: item.nav_date)
    except (
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
        ValidationError,
    ) as error:
        raise ProviderPayloadError("东方财富基金历史结构异常") from error


def _parse_sina_official_history(
    text: str,
    *,
    ticker: str,
    fetched_at: datetime,
) -> FundOfficialNavSnapshot:
    """解析新浪最新两条净值，作为东方财富历史接口异常时的免费回退。"""
    try:
        payload = json.loads(text, parse_float=Decimal)
        if payload["result"]["status"]["code"] != 0:
            raise ValueError("新浪基金净值响应状态异常")
        rows = payload["result"]["data"]["data"]
        current = rows[0]
        previous_nav = rows[1]["jjjz"] if len(rows) >= 2 else None
        return FundOfficialNavSnapshot.model_validate(
            {
                "ticker": ticker,
                "unit_nav": current["jjjz"],
                "accumulated_nav": current.get("ljjz") or None,
                "change_rate": (
                    _relative_change(current["jjjz"], previous_nav)
                    if previous_nav not in {None, ""}
                    else None
                ),
                "nav_date": date.fromisoformat(current["fbrq"][:10]),
                "fetched_at": fetched_at,
                "source": "sina_fund_official_single",
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
        raise ProviderPayloadError("新浪单基金官方净值结构异常") from error


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
            previous_nav = row[5] if len(row) > 5 else None
            snapshots.append(
                FundOfficialNavSnapshot.model_validate(
                    {
                        "ticker": ticker,
                        "unit_nav": unit_nav,
                        "accumulated_nav": row[4] or None,
                        "change_rate": (
                            _relative_change(unit_nav, previous_nav)
                            if previous_nav not in {None, ""}
                            else _optional_percentage_ratio(row[7] if len(row) > 7 else None)
                        ),
                        "nav_date": nav_date,
                        "fetched_at": datetime.now(UTC),
                        "source": "eastmoney_fund_official_bulk",
                    }
                )
            )
        except ValidationError as error:
            raise ProviderPayloadError("基金官方净值字段校验失败") from error
    return snapshots


def _percentage_ratio(value: object) -> Decimal:
    """把第三方百分数值转换为内部比值口径。"""
    try:
        return Decimal(str(value)) / Decimal("100")
    except (InvalidOperation, ValueError) as error:
        raise ValueError("基金涨跌率不是有效数字") from error


def _optional_percentage_ratio(value: object) -> Decimal | None:
    """转换可选日涨跌百分数，供应商缺失时保留空值。"""
    if value in {None, "", "--"}:
        return None
    return _percentage_ratio(value)


def _relative_change(current_value: object, previous_value: object) -> Decimal:
    """用两个原始净值计算精确涨跌率，避免百分比四舍五入放大金额误差。"""
    try:
        current = Decimal(str(current_value))
        previous = Decimal(str(previous_value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("基金净值不是有效数字") from error
    if current <= 0 or previous <= 0:
        raise ValueError("基金净值必须大于零")
    return current / previous - Decimal("1")


def _parse_estimated_fallback(
    text: str,
    *,
    ticker: str,
    fetched_at: datetime,
) -> FundEstimatedNavSnapshot:
    """解析基金速查网的净值估算字段，并拒绝缺时点或缺涨跌率的数据。"""
    fields = [field.strip() for field in text.strip().split("|")]
    if len(fields) < 11:
        raise ProviderPayloadError("基金估算回退响应字段数量异常")
    estimated_nav = fields[7]
    percentage = fields[5].removesuffix("%")
    base_nav = fields[1]
    estimate_date = fields[9]
    estimate_time = fields[10]
    if not all((estimated_nav, percentage, base_nav, estimate_date, estimate_time)):
        raise ProviderPayloadError("基金估算回退响应缺少必要字段")
    try:
        as_of = (
            datetime.strptime(f"{estimate_date} {estimate_time}", "%Y-%m-%d %H:%M:%S")
            .replace(tzinfo=_SHANGHAI_TIMEZONE)
            .astimezone(UTC)
        )
        return FundEstimatedNavSnapshot.model_validate(
            {
                "ticker": ticker,
                "estimated_nav": estimated_nav,
                "change_rate": _relative_change(estimated_nav, base_nav),
                "as_of_at": as_of,
                "fetched_at": fetched_at,
                "source": "dayfund_fund_estimate",
            }
        )
    except (ValueError, ValidationError) as error:
        raise ProviderPayloadError("基金估算回退字段校验失败") from error
