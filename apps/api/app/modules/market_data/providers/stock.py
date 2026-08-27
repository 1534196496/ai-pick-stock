"""腾讯首选与新浪回退的 A 股主数据和行情适配器。"""

import json
import math
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.modules.instruments.enums import AssetType, Currency, Exchange, Market
from app.modules.market_data.providers.http import (
    ProviderHttpClient,
    ProviderPayloadError,
    ProviderUnavailableError,
)
from app.modules.market_data.providers.schemas import (
    ProviderInstrument,
    StockDailyBarSnapshot,
    StockPriceSnapshot,
    StockQuoteRequest,
)

_TENCENT_RANK_URL = "https://proxy.finance.qq.com/cgi/cgi-bin/rank/hs/getBoardRankList"
_TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="
_SINA_QUOTE_URL = "https://hq.sinajs.cn/list="
_EASTMONEY_DAILY_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
_SINA_DAILY_URL = (
    "https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_data=/CN_MarketDataService.getKLineData"
)
_HEADERS = {"User-Agent": "ai-pick-stock-worker/2.0", "Referer": "https://stockapp.finance.qq.com/"}


class StockProvider:
    """同步 A 股主数据，并为活跃标的提供带回退的最新价。"""

    def __init__(self, http: ProviderHttpClient, *, page_size: int = 200) -> None:
        """注入共享 HTTP 边界和保守分页大小。"""
        self._http = http
        self._page_size = page_size

    async def fetch_instruments(self) -> list[ProviderInstrument]:
        """分页读取腾讯 A 股榜单并按代码去重。"""
        first = await self._fetch_rank_page(offset=0)
        total = _required_int(first, "total")
        rows = _required_list(first, "rank_list")
        for page in range(1, math.ceil(total / self._page_size)):
            payload = await self._fetch_rank_page(offset=page * self._page_size)
            rows.extend(_required_list(payload, "rank_list"))
        instruments: dict[tuple[Exchange, str], ProviderInstrument] = {}
        for row in rows:
            instrument = _parse_tencent_instrument(row)
            instruments[(instrument.exchange, instrument.ticker)] = instrument
        return list(instruments.values())

    async def fetch_stock_prices(
        self,
        requests: list[StockQuoteRequest],
    ) -> list[StockPriceSnapshot]:
        """腾讯批量行情失败时整批切换新浪，避免混合不一致时点。"""
        if not requests:
            return []
        try:
            return await self._fetch_tencent_quotes(requests)
        except (ProviderUnavailableError, ProviderPayloadError, ValidationError):
            return await self._fetch_sina_quotes(requests)

    async def fetch_stock_daily_bars(
        self,
        request: StockQuoteRequest,
        *,
        limit: int = 250,
    ) -> list[StockDailyBarSnapshot]:
        """读取单只 A 股最近前复权日线并校验价格范围。"""
        if not 20 <= limit <= 500:
            raise ValueError("股票历史条数必须在 20 到 500 之间")
        secid = _eastmoney_secid(request)
        try:
            response = await self._http.get(
                _EASTMONEY_DAILY_URL,
                params={
                    "secid": secid,
                    "klt": "101",
                    "fqt": "1",
                    "lmt": str(limit),
                    "end": "20500101",
                    "fields1": "f1,f2,f3,f4,f5,f6",
                    "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                },
                headers={**_HEADERS, "Referer": "https://quote.eastmoney.com/"},
                encoding="utf-8",
            )
            return _parse_eastmoney_daily_bars(response.text(), ticker=request.ticker)
        except (ProviderUnavailableError, ProviderPayloadError):
            response = await self._http.get(
                _SINA_DAILY_URL,
                params={
                    "symbol": _vendor_symbol(request),
                    "scale": "240",
                    "ma": "no",
                    "datalen": str(limit),
                },
                headers={**_HEADERS, "Referer": "https://finance.sina.com.cn/"},
                encoding="utf-8",
            )
            return _parse_sina_daily_bars(response.text(), ticker=request.ticker)

    async def _fetch_rank_page(self, *, offset: int) -> dict[str, Any]:
        """读取并校验腾讯榜单的 data 对象。"""
        response = await self._http.get(
            _TENCENT_RANK_URL,
            params={
                "_appver": "11.17.0",
                "board_code": "aStock",
                "sort_type": "price",
                "direct": "down",
                "offset": str(offset),
                "count": str(self._page_size),
            },
            headers=_HEADERS,
        )
        try:
            payload = json.loads(response.text())
            if payload.get("code") != 0 or not isinstance(payload.get("data"), dict):
                raise ProviderPayloadError("腾讯榜单状态异常")
            return cast(dict[str, Any], payload["data"])
        except (json.JSONDecodeError, AttributeError, TypeError) as error:
            raise ProviderPayloadError("腾讯榜单 JSON 结构异常") from error

    async def _fetch_tencent_quotes(
        self,
        requests: list[StockQuoteRequest],
    ) -> list[StockPriceSnapshot]:
        """解析腾讯波浪线文本行情。"""
        symbols = ",".join(_vendor_symbol(request) for request in requests)
        response = await self._http.get(
            _TENCENT_QUOTE_URL + symbols,
            headers=_HEADERS,
            encoding="gb18030",
        )
        snapshots = [_parse_tencent_quote(line) for line in response.text().splitlines() if line]
        if len(snapshots) != len(requests):
            raise ProviderPayloadError("腾讯行情返回数量不完整")
        return snapshots

    async def _fetch_sina_quotes(
        self,
        requests: list[StockQuoteRequest],
    ) -> list[StockPriceSnapshot]:
        """解析新浪逗号文本回退行情。"""
        symbols = ",".join(_vendor_symbol(request) for request in requests)
        response = await self._http.get(
            _SINA_QUOTE_URL + symbols,
            headers={**_HEADERS, "Referer": "https://finance.sina.com.cn/"},
            encoding="gb18030",
        )
        snapshots = [_parse_sina_quote(line) for line in response.text().splitlines() if line]
        if len(snapshots) != len(requests):
            raise ProviderPayloadError("新浪行情返回数量不完整")
        return snapshots


def _parse_tencent_instrument(raw: object) -> ProviderInstrument:
    """把腾讯榜单行转换为标准资产身份。"""
    if not isinstance(raw, dict):
        raise ProviderPayloadError("腾讯榜单行不是对象")
    code = raw.get("code")
    name = raw.get("name")
    if not isinstance(code, str) or not isinstance(name, str) or len(code) < 3:
        raise ProviderPayloadError("腾讯榜单缺少代码或名称")
    exchange = _exchange_from_prefix(code[:2])
    return ProviderInstrument(
        asset_type=AssetType.STOCK,
        market=Market.CN,
        exchange=exchange,
        ticker=code[2:],
        name=name.strip(),
        currency=Currency.CNY,
        source="tencent_stock_rank",
        source_updated_at=datetime.now(UTC),
    )


def _parse_tencent_quote(line: str) -> StockPriceSnapshot:
    """从腾讯行情字段提取 ticker、最新价和业务时间。"""
    match = re.search(r'="(.*)";?$', line)
    if match is None:
        raise ProviderPayloadError("腾讯行情文本包装异常")
    fields = match.group(1).split("~")
    if len(fields) <= 30:
        raise ProviderPayloadError("腾讯行情字段数量不足")
    try:
        as_of = (
            datetime.strptime(fields[30], "%Y%m%d%H%M%S")
            .replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            .astimezone(UTC)
        )
        return StockPriceSnapshot.model_validate(
            {
                "ticker": fields[2],
                "value": fields[3],
                "change_rate": _change_rate(fields[3], fields[4]),
                "as_of_at": as_of,
                "fetched_at": datetime.now(UTC),
                "source": "tencent_stock_quote",
            }
        )
    except (ValueError, ValidationError) as error:
        raise ProviderPayloadError("腾讯行情字段校验失败") from error


def _parse_sina_quote(line: str) -> StockPriceSnapshot:
    """从新浪行情字段提取最新价和日期时间。"""
    match = re.match(r'var hq_str_[a-z]{2}([^=]+)="(.*)";?', line)
    if match is None:
        raise ProviderPayloadError("新浪行情文本包装异常")
    ticker, body = match.groups()
    fields = body.split(",")
    if len(fields) <= 31:
        raise ProviderPayloadError("新浪行情字段数量不足")
    try:
        as_of = (
            datetime.strptime(
                f"{fields[30]} {fields[31]}",
                "%Y-%m-%d %H:%M:%S",
            )
            .replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            .astimezone(UTC)
        )
        return StockPriceSnapshot.model_validate(
            {
                "ticker": ticker,
                "value": fields[3],
                "change_rate": _change_rate(fields[3], fields[2]),
                "as_of_at": as_of,
                "fetched_at": datetime.now(UTC),
                "source": "sina_stock_quote",
            }
        )
    except (ValueError, ValidationError) as error:
        raise ProviderPayloadError("新浪行情字段校验失败") from error


def _parse_eastmoney_daily_bars(
    text: str,
    *,
    ticker: str,
) -> list[StockDailyBarSnapshot]:
    """解析东方财富前复权日线，并从相邻记录补出昨收字段。"""
    try:
        payload = json.loads(text, parse_float=Decimal)
        if payload.get("rc") != 0:
            raise ValueError("东方财富日线响应状态异常")
        data = payload["data"]
        rows = data["klines"]
        if not isinstance(rows, list) or not rows:
            raise ValueError("东方财富日线数据为空")
        snapshots: list[StockDailyBarSnapshot] = []
        previous_close = str(data.get("preKPrice")) if data.get("preKPrice") else None
        for raw in rows:
            if not isinstance(raw, str):
                raise ValueError("东方财富日线记录类型异常")
            row = raw.split(",")
            if len(row) < 11:
                raise ValueError("东方财富日线字段数量异常")
            snapshot = StockDailyBarSnapshot.model_validate(
                {
                    "ticker": ticker,
                    "trade_date": row[0],
                    "open": row[1],
                    "close": row[2],
                    "high": row[3],
                    "low": row[4],
                    "volume": row[5],
                    "previous_close": previous_close,
                    "turnover": row[6],
                    "source": "eastmoney_stock_qfq_daily",
                }
            )
            snapshots.append(snapshot)
            previous_close = str(snapshot.close)
        return snapshots
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, ValidationError) as error:
        raise ProviderPayloadError("东方财富股票日线结构异常") from error


def _parse_sina_daily_bars(
    text: str,
    *,
    ticker: str,
) -> list[StockDailyBarSnapshot]:
    """解析新浪未复权日线，作为前复权来源不可用时的保守回退。"""
    try:
        start = text.index("=([") + 2
        end = text.rindex(");")
        rows = json.loads(text[start:end], parse_float=Decimal)
        if not isinstance(rows, list) or not rows:
            raise ValueError("新浪日线数据为空")
        snapshots: list[StockDailyBarSnapshot] = []
        previous_close: str | None = None
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("新浪日线记录类型异常")
            snapshot = StockDailyBarSnapshot.model_validate(
                {
                    "ticker": ticker,
                    "trade_date": row["day"],
                    "open": row["open"],
                    "close": row["close"],
                    "high": row["high"],
                    "low": row["low"],
                    "volume": row.get("volume"),
                    "previous_close": previous_close,
                    "turnover": None,
                    "source": "sina_stock_daily",
                }
            )
            snapshots.append(snapshot)
            previous_close = str(snapshot.close)
        return snapshots
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, ValidationError) as error:
        raise ProviderPayloadError("新浪股票日线结构异常") from error


def _change_rate(current: str, previous_close: str) -> Decimal:
    """使用最新价和昨收价计算比值口径的今日涨跌率。"""
    try:
        current_value = Decimal(current)
        previous_value = Decimal(previous_close)
        if previous_value <= 0:
            raise ValueError("昨收价必须大于零")
        return (current_value - previous_value) / previous_value
    except (InvalidOperation, ValueError) as error:
        raise ProviderPayloadError("行情涨跌率字段异常") from error


def _vendor_symbol(request: StockQuoteRequest) -> str:
    """按明确交易所生成供应商代码前缀。"""
    prefix = {Exchange.SSE: "sh", Exchange.SZSE: "sz", Exchange.BSE: "bj"}.get(request.exchange)
    if prefix is None:
        raise ProviderPayloadError("基金交易所不能请求股票行情")
    return prefix + request.ticker


def _eastmoney_secid(request: StockQuoteRequest) -> str:
    """按交易所生成东方财富日线所需的市场编号。"""
    market = "1" if request.exchange is Exchange.SSE else "0"
    if request.exchange not in {Exchange.SSE, Exchange.SZSE, Exchange.BSE}:
        raise ProviderPayloadError("基金交易所不能请求股票日线")
    return f"{market}.{request.ticker}"


def _exchange_from_prefix(prefix: str) -> Exchange:
    """把供应商前缀映射为公开交易所枚举。"""
    try:
        return {"sh": Exchange.SSE, "sz": Exchange.SZSE, "bj": Exchange.BSE}[prefix]
    except KeyError as error:
        raise ProviderPayloadError("未知股票交易所前缀") from error


def _required_int(payload: dict[str, Any], key: str) -> int:
    """读取必须为整数或整数字符串的字段。"""
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ProviderPayloadError(f"{key} 类型异常")
    try:
        return int(value)
    except ValueError as error:
        raise ProviderPayloadError(f"{key} 类型异常") from error


def _required_list(payload: dict[str, Any], key: str) -> list[object]:
    """读取必须存在的列表字段并复制，避免修改原响应。"""
    value = payload.get(key)
    if not isinstance(value, list):
        raise ProviderPayloadError(f"{key} 类型异常")
    return list(value)
