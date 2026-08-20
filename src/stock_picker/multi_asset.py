from __future__ import annotations

from datetime import date, datetime
from io import StringIO

import numpy as np
import pandas as pd
import requests
from zoneinfo import ZoneInfo

from .db import Database


MARKET_GROUPS = {
    "全球股指": {
        "标普500": "^GSPC", "纳斯达克": "^IXIC", "道琼斯": "^DJI",
        "英国富时100": "^FTSE", "德国DAX": "^GDAXI", "法国CAC40": "^FCHI",
        "日经225": "^N225", "恒生指数": "^HSI", "上证指数": "000001.SS",
        "深证成指": "399001.SZ", "印度SENSEX": "^BSESN", "澳洲ASX200": "^AXJO",
    },
    "商品": {
        "黄金期货连续合约": "GC=F", "白银期货连续合约": "SI=F", "WTI原油连续合约": "CL=F",
        "布伦特原油连续合约": "BZ=F", "铜期货连续合约": "HG=F", "天然气期货连续合约": "NG=F",
    },
    "债券ETF": {
        "美国长期国债 TLT": "TLT", "美国中期国债 IEF": "IEF",
        "美国短期国债 SHY": "SHY", "美国综合债 AGG": "AGG",
        "全球综合债 BNDW": "BNDW", "投资级公司债 LQD": "LQD",
        "高收益债 HYG": "HYG", "通胀保值债 TIP": "TIP",
    },
    "全球ETF": {
        "全球股票 VT": "VT", "美国大盘 SPY": "SPY", "纳指100 QQQ": "QQQ",
        "发达市场 VEA": "VEA", "新兴市场 VWO": "VWO", "中国大盘 FXI": "FXI",
        "黄金ETF GLD": "GLD", "房地产 VNQ": "VNQ",
    },
}

EXCHANGE_CALENDARS = {
    "SNP":"XNYS", "DJI":"XNYS", "NIM":"XNYS", "NMS":"XNYS", "NYQ":"XNYS", "NGM":"XNYS", "PCX":"XNYS",
    "HKG":"XHKG", "OSA":"XTKS", "JPX":"XTKS", "SHH":"XSHG", "SHZ":"XSHG",
    "FGI":"XLON", "LSE":"XLON", "PAR":"XPAR", "GER":"XFRA", "AMS":"XAMS", "EBS":"XSWX",
    "BSE":"XBOM", "ASX":"XASX", "TOR":"XTSE", "CMX":"CMES", "NYM":"CMES",
}


def market_session_lag(latest_date: date, market_today: date, exchange_name: str | None) -> tuple[int, str]:
    """Return completed trading-session lag, using exchange holidays when known."""
    calendar_name = EXCHANGE_CALENDARS.get(str(exchange_name or "").upper())
    if calendar_name:
        try:
            import exchange_calendars as xcals
            calendar = xcals.get_calendar(calendar_name)
            sessions = calendar.sessions_in_range(pd.Timestamp(latest_date), pd.Timestamp(market_today))
            return max(0, len(sessions) - 1), calendar_name
        except Exception:
            pass
    return max(0, len(pd.bdate_range(latest_date, market_today)) - 1), "weekday_fallback"


def yahoo_history(symbol: str, period: str = "2y") -> pd.DataFrame:
    try:
        direct = yahoo_chart_history(symbol.strip().upper(), period)
        if not direct.empty:
            return direct
    except Exception:
        pass
    import yfinance as yf

    ticker = symbol.strip().upper()
    raw = yf.download(
        ticker, period=period, interval="1d", auto_adjust=True,
        progress=False, threads=False, timeout=20, multi_level_index=False,
    )
    if raw is None or raw.empty:
        return pd.DataFrame()
    raw = raw.reset_index()
    rename = {str(c).lower(): str(c) for c in raw.columns}
    date_column = rename.get("date") or rename.get("datetime")
    close_column = rename.get("close")
    if not date_column or not close_column:
        return pd.DataFrame()
    frame = pd.DataFrame({
        "date": pd.to_datetime(raw[date_column], errors="coerce").dt.tz_localize(None),
        "open": pd.to_numeric(raw[rename["open"]], errors="coerce"),
        "high": pd.to_numeric(raw[rename["high"]], errors="coerce"),
        "low": pd.to_numeric(raw[rename["low"]], errors="coerce"),
        "close": pd.to_numeric(raw[close_column], errors="coerce"),
        "volume": pd.to_numeric(raw[rename["volume"]], errors="coerce") if "volume" in rename else np.nan,
    }).dropna(subset=["date", "close"])
    frame["ma20"] = frame.close.rolling(20).mean()
    frame["ma60"] = frame.close.rolling(60).mean()
    frame["drawdown"] = frame.close / frame.close.cummax() - 1
    return frame


def yahoo_chart_history(symbol: str, period: str = "2y") -> pd.DataFrame:
    """Direct chart endpoint fallback when the yfinance client is rate-limited."""
    encoded = requests.utils.quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}"
    response = requests.get(
        url,
        params={"range": period, "interval": "1d", "events": "div,splits"},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=25,
    )
    response.raise_for_status()
    result = response.json().get("chart", {}).get("result")
    if not result:
        return pd.DataFrame()
    data = result[0]
    timestamps = data.get("timestamp") or []
    indicators = data.get("indicators", {})
    quote = (indicators.get("quote") or [{}])[0]
    adjusted = (indicators.get("adjclose") or [{}])[0].get("adjclose")
    if not timestamps or not quote.get("close"):
        return pd.DataFrame()
    length = len(timestamps)
    values = lambda key: (quote.get(key) or [None] * length)[:length]
    raw_close = pd.to_numeric(pd.Series(values("close")), errors="coerce")
    adjusted_close = pd.to_numeric(pd.Series(adjusted[:length] if adjusted else values("close")), errors="coerce")
    ratio = adjusted_close / raw_close.replace(0, np.nan)
    frame = pd.DataFrame({
        "date": pd.to_datetime(timestamps, unit="s", utc=True).tz_convert(None),
        # Adjust OHLC with the same factor as adjusted close so a chart never
        # mixes raw candles with total-return close.
        "open": pd.to_numeric(pd.Series(values("open")), errors="coerce") * ratio,
        "high": pd.to_numeric(pd.Series(values("high")), errors="coerce") * ratio,
        "low": pd.to_numeric(pd.Series(values("low")), errors="coerce") * ratio,
        "close": adjusted_close, "volume": values("volume"),
    })
    for column in ["open", "high", "low", "close", "volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["date", "close"]).sort_values("date")
    frame["ma20"] = frame.close.rolling(20).mean()
    frame["ma60"] = frame.close.rolling(60).mean()
    frame["drawdown"] = frame.close / frame.close.cummax() - 1
    frame.attrs["metadata"] = data.get("meta", {})
    frame.attrs["source"] = "Yahoo Finance chart API"
    frame.attrs["price_kind"] = "adjusted_total_return_proxy"
    return frame


def cached_asset_history(db: Database, symbol: str, refresh: bool = False, period: str = "2y") -> tuple[pd.DataFrame, str]:
    symbol = symbol.strip().upper()
    # Rows created before price lineage existed remain in the database for
    # audit, but must never be mixed into adjusted-return calculations.
    cached = db.query_df(
        "SELECT * FROM asset_prices WHERE symbol=? AND price_kind NOT IN ('legacy_unknown','unknown') ORDER BY price_date",
        (symbol,),
    )
    cache_is_today = False
    if not cached.empty:
        fetched = pd.to_datetime(cached["fetched_at"], errors="coerce").max()
        meta_for_clock = db.query_df("SELECT exchange_timezone FROM asset_metadata WHERE symbol=?", (symbol,))
        clock_tz = str(meta_for_clock.iloc[0]["exchange_timezone"]) if not meta_for_clock.empty and meta_for_clock.iloc[0]["exchange_timezone"] else "UTC"
        try:
            market_today_for_cache = datetime.now(ZoneInfo(clock_tz)).date()
            fetched_dt = fetched.to_pydatetime()
            if fetched_dt.tzinfo is None:
                # Historical rows were written in machine-local time. Python's
                # astimezone() attaches the actual local timezone; never assume UTC.
                fetched_dt = fetched_dt.astimezone()
            fetched_market_date = fetched_dt.astimezone(ZoneInfo(clock_tz)).date()
            cache_is_today = pd.notna(fetched) and fetched_market_date == market_today_for_cache
        except Exception:
            cache_is_today = pd.notna(fetched) and fetched.date() == date.today()
    source = str(cached.iloc[-1]["source"]) if not cached.empty else ""
    expected_days = {"1mo": 20, "3mo": 60, "6mo": 120, "1y": 240, "2y": 480, "5y": 1200}.get(period, 240)
    coverage_ok = len(cached) >= expected_days
    refresh_error = None
    if refresh or cached.empty or not cache_is_today or not coverage_ok:
        try:
            fresh = yahoo_history(symbol, period)
            if not fresh.empty:
                source = fresh.attrs.get("source", "Yahoo Finance client auto-adjusted")
                fetched_at = datetime.now().astimezone().isoformat(timespec="seconds")
                db.upsert_asset_prices(symbol, fresh, source, fetched_at, fresh.attrs.get("price_kind", "adjusted_total_return_proxy"))
                metadata = dict(fresh.attrs.get("metadata", {}))
                metadata["instrumentType"] = metadata.get("instrumentType") or fresh.attrs.get("price_kind")
                db.upsert_asset_metadata(symbol, metadata, source, fetched_at)
                cached = db.query_df(
                    "SELECT * FROM asset_prices WHERE symbol=? AND price_kind NOT IN ('legacy_unknown','unknown') ORDER BY price_date",
                    (symbol,),
                )
            elif cached.empty:
                raise RuntimeError(f"{symbol} 数据源返回空响应")
            else:
                refresh_error = "EmptyResponse"
        except Exception as error:
            refresh_error = type(error).__name__
            if cached.empty:
                raise
    if cached.empty:
        return pd.DataFrame(), source
    frame = pd.DataFrame({
        "date": pd.to_datetime(cached["price_date"]),
        "open": cached["open"], "high": cached["high"], "low": cached["low"],
        "close": cached["close"], "volume": cached["volume"],
    })
    frame["ma20"] = frame.close.rolling(20).mean()
    frame["ma60"] = frame.close.rolling(60).mean()
    frame["drawdown"] = frame.close / frame.close.cummax() - 1
    meta = db.query_df("SELECT exchange_timezone, exchange_name, fetched_at FROM asset_metadata WHERE symbol=?", (symbol,))
    timezone_name = str(meta.iloc[0]["exchange_timezone"]) if not meta.empty and meta.iloc[0]["exchange_timezone"] else "UTC"
    try:
        market_today = datetime.now(ZoneInfo(timezone_name)).date()
    except Exception:
        market_today = date.today()
    latest_date = frame.date.max().date()
    exchange_name = str(meta.iloc[0]["exchange_name"]) if not meta.empty and meta.iloc[0]["exchange_name"] else None
    business_lag, calendar_name = market_session_lag(latest_date, market_today, exchange_name) if latest_date <= market_today else (0, "future_date")
    freshness = "stale" if refresh_error or business_lag > 3 else "fresh"
    frame.attrs["cache_status"] = freshness
    frame.attrs["refresh_error"] = refresh_error
    frame.attrs["business_day_lag"] = business_lag
    frame.attrs["calendar"] = calendar_name
    if freshness == "stale":
        reason = f"刷新失败：{refresh_error}" if refresh_error else f"距离最新预期交易日 {business_lag} 个交易时段"
        source = f"{source} · 陈旧缓存（{reason}）"
    return frame, source


def asset_summary(frame: pd.DataFrame) -> dict[str, float]:
    close = frame.close
    returns = close.pct_change()
    return {
        "last": float(close.iloc[-1]),
        "return_1d": float(close.iloc[-1] / close.iloc[-2] - 1) if len(close) >= 2 else np.nan,
        "return_1m": float(close.iloc[-1] / close.iloc[-22] - 1) if len(close) >= 22 else np.nan,
        "return_3m": float(close.iloc[-1] / close.iloc[-66] - 1) if len(close) >= 66 else np.nan,
        "return_1y": float(close.iloc[-1] / close.iloc[-min(len(close), 252)] - 1) if len(close) >= 240 else np.nan,
        "volatility": float(returns.tail(60).std() * np.sqrt(252)),
        "max_drawdown": float(frame.drawdown.min()),
    }


def market_snapshot(group: str, db: Database | None = None) -> pd.DataFrame:
    rows = []
    for name, symbol in MARKET_GROUPS[group].items():
        try:
            history, source = cached_asset_history(db, symbol, period="1y") if db else (yahoo_history(symbol, "1y"), "Yahoo Finance")
            if history.empty:
                continue
            summary = asset_summary(history)
            metadata = db.query_df("SELECT currency, exchange_timezone FROM asset_metadata WHERE symbol=?", (symbol,)) if db else pd.DataFrame()
            currency = metadata.iloc[0]["currency"] if not metadata.empty else None
            timezone = metadata.iloc[0]["exchange_timezone"] if not metadata.empty else None
            rows.append({"name": name, "symbol": symbol, "status": history.attrs.get("cache_status", "fresh"), "as_of": history.date.max().date().isoformat(), "source": source, "currency": currency, "timezone": timezone, **summary})
        except Exception as error:
            rows.append({"name": name, "symbol": symbol, "status": "failed", "error": type(error).__name__})
    return pd.DataFrame(rows)


def treasury_yield_curve(year: int | None = None) -> pd.DataFrame:
    year = year or date.today().year
    url = (
        f"https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
        f"daily-treasury-rates.csv/{year}/all?type=daily_treasury_yield_curve"
        f"&field_tdr_date_value={year}&page&_format=csv"
    )
    response = requests.get(url, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    frame = pd.read_csv(StringIO(response.text))
    if frame.empty or "Date" not in frame.columns:
        return pd.DataFrame()
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    for column in frame.columns[1:]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna(subset=["Date"]).sort_values("Date")


def cached_treasury_yield_curve(db: Database, refresh: bool = False) -> pd.DataFrame:
    cached = db.query_df("SELECT * FROM macro_observations WHERE series_id LIKE 'UST_%' ORDER BY observation_date")
    if refresh:
        fresh = treasury_yield_curve()
        fetched_at = datetime.now().astimezone().isoformat(timespec="seconds")
        rows = []
        for point in fresh.itertuples(index=False):
            observation_date = point[0].strftime("%Y-%m-%d")
            for column, value in zip(fresh.columns[1:], point[1:]):
                rows.append((f"UST_{column.replace(' ', '_')}", observation_date, value, "percent", "U.S. Treasury official CSV", fetched_at))
        db.upsert_macro_observations(rows)
        cached = db.query_df("SELECT * FROM macro_observations WHERE series_id LIKE 'UST_%' ORDER BY observation_date")
    if cached.empty:
        return pd.DataFrame()
    cached = cached.copy()
    cached["maturity"] = cached.series_id.str.removeprefix("UST_").str.replace("_", " ")
    frame = cached.pivot(index="observation_date", columns="maturity", values="value").reset_index().rename(columns={"observation_date":"Date"})
    frame["Date"] = pd.to_datetime(frame.Date)
    frame.columns.name = None
    return frame.sort_values("Date")


def latest_yield_curve(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    latest = frame.iloc[-1]
    maturities = ["1 Mo", "3 Mo", "6 Mo", "1 Yr", "2 Yr", "3 Yr", "5 Yr", "7 Yr", "10 Yr", "20 Yr", "30 Yr"]
    return pd.DataFrame({"期限": [m for m in maturities if m in frame.columns], "收益率": [latest[m] for m in maturities if m in frame.columns]})


def asset_metadata(db: Database, symbol: str) -> dict:
    frame = db.query_df("SELECT * FROM asset_metadata WHERE symbol=?", (symbol.strip().upper(),))
    return frame.iloc[0].to_dict() if not frame.empty else {}


def search_assets(query: str, limit: int = 12) -> pd.DataFrame:
    if not query.strip():
        return pd.DataFrame()
    response = requests.get(
        "https://query1.finance.yahoo.com/v1/finance/search",
        params={"q": query.strip(), "quotesCount": limit, "newsCount": 0, "enableFuzzyQuery": "false"},
        headers={"User-Agent": "Mozilla/5.0"}, timeout=20,
    )
    response.raise_for_status()
    rows = []
    for quote in response.json().get("quotes", []):
        symbol = quote.get("symbol")
        if not symbol:
            continue
        rows.append({
            "symbol": symbol, "name": quote.get("longname") or quote.get("shortname") or symbol,
            "exchange": quote.get("exchDisp") or quote.get("exchange"),
            "asset_type": quote.get("typeDisp") or quote.get("quoteType"),
        })
    return pd.DataFrame(rows)


SEARCH_ALIASES = {
    "腾讯": ("0700.HK", "腾讯控股", "港交所", "股票"),
    "阿里": ("BABA", "阿里巴巴", "NYSE", "股票"),
    "苹果": ("AAPL", "Apple Inc.", "NASDAQ", "股票"),
    "微软": ("MSFT", "Microsoft Corp.", "NASDAQ", "股票"),
    "标普": ("^GSPC", "标普500指数", "S&P", "指数"),
    "黄金": ("GC=F", "黄金期货连续合约", "COMEX", "商品期货代理"),
    "美债": ("TLT", "美国长期国债ETF", "NASDAQ", "债券ETF"),
    "全球股票": ("VT", "全球股票ETF", "NYSE Arca", "ETF"),
}


def unified_search(db: Database, query: str, limit: int = 15) -> pd.DataFrame:
    query = query.strip()
    if not query:
        return pd.DataFrame()
    rows = []
    for alias, (symbol, name, exchange, asset_type) in SEARCH_ALIASES.items():
        if query.lower() in alias.lower() or query.lower() in name.lower() or query.upper() == symbol:
            rows.append({"symbol": symbol, "name": name, "exchange": exchange, "asset_type": asset_type, "source": "本地核验别名"})
    local = db.query_df("SELECT code, name FROM instruments WHERE code LIKE ? OR name LIKE ? LIMIT ?", (f"%{query}%", f"%{query}%", limit))
    for row in local.itertuples():
        suffix = ".SS" if row.code.startswith(("60", "68")) else ".SZ"
        rows.append({"symbol": row.code + suffix, "name": row.name, "exchange": "A股", "asset_type": "股票", "source": "本地A股证券库"})
    try:
        remote = search_assets(query, limit)
        for row in remote.itertuples():
            rows.append({"symbol": row.symbol, "name": row.name, "exchange": row.exchange, "asset_type": row.asset_type, "source": "Yahoo Finance Search"})
    except Exception:
        pass
    return pd.DataFrame(rows).drop_duplicates("symbol").head(limit) if rows else pd.DataFrame()


def fundamental_timeseries(symbol: str) -> pd.DataFrame:
    """Public valuation/financial time series; absent fields remain absent."""
    end = int(datetime.now().timestamp())
    start = end - 5 * 366 * 86400
    types = [
        "trailingMarketCap", "trailingPeRatio", "trailingEnterprisesValueEBITDARatio",
        "annualTotalRevenue", "annualNetIncome", "annualFreeCashFlow",
        "annualTotalAssets", "annualStockholdersEquity",
    ]
    response = requests.get(
        f"https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{requests.utils.quote(symbol, safe='')}",
        params={"symbol": symbol, "type": ",".join(types), "merge": "false", "period1": start, "period2": end},
        headers={"User-Agent": "Mozilla/5.0"}, timeout=25,
    )
    response.raise_for_status()
    rows = []
    for result in response.json().get("timeseries", {}).get("result", []):
        meta = result.get("meta", {})
        field = (meta.get("type") or [None])[0]
        if not field:
            continue
        for point in result.get(field, []):
            reported = point.get("reportedValue", {})
            value = reported.get("raw", point.get("reportedValue", point.get("value")))
            rows.append({"date": point.get("asOfDate") or pd.to_datetime(point.get("timestamp"), unit="s").date().isoformat(), "field": field, "value": value, "currency": reported.get("currencyCode")})
    frame = pd.DataFrame(rows)
    return frame.sort_values(["date", "field"]) if not frame.empty else frame
