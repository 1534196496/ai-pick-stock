"""腾讯首选与新浪回退的 A 股主数据和行情适配器。"""

import json
import math
import re
from datetime import UTC, datetime
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
    StockPriceSnapshot,
    StockQuoteRequest,
)

_TENCENT_RANK_URL = "https://proxy.finance.qq.com/cgi/cgi-bin/rank/hs/getBoardRankList"
_TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="
_SINA_QUOTE_URL = "https://hq.sinajs.cn/list="
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
                "as_of_at": as_of,
                "fetched_at": datetime.now(UTC),
                "source": "sina_stock_quote",
            }
        )
    except (ValueError, ValidationError) as error:
        raise ProviderPayloadError("新浪行情字段校验失败") from error


def _vendor_symbol(request: StockQuoteRequest) -> str:
    """按明确交易所生成供应商代码前缀。"""
    prefix = {Exchange.SSE: "sh", Exchange.SZSE: "sz", Exchange.BSE: "bj"}.get(request.exchange)
    if prefix is None:
        raise ProviderPayloadError("基金交易所不能请求股票行情")
    return prefix + request.ticker


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
