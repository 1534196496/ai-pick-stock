from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
import requests


SEMICONDUCTOR_MARKETS = {
    "SK海力士 ADR": {"symbol": "SKHY", "currency": "USD", "calendar": "XNYS"},
    "美光科技": {"symbol": "MU", "currency": "USD", "calendar": "XNYS"},
    "闪迪": {"symbol": "SNDK", "currency": "USD", "calendar": "XNYS"},
    "费城半导体": {"symbol": "^SOX", "currency": "USD", "calendar": "XNYS"},
}

INTRADAY_SOURCE = "Yahoo Finance Chart API（免费聚合行情，可能延迟）"


def _numeric(values: list[Any] | None, length: int) -> pd.Series:
    padded = list(values or [])[:length]
    padded.extend([None] * (length - len(padded)))
    return pd.to_numeric(pd.Series(padded), errors="coerce")


def fetch_intraday(
    symbol: str,
    *,
    range_: str = "1d",
    interval: str = "1m",
    timeout: int = 15,
    now: datetime | None = None,
) -> pd.DataFrame:
    """Fetch genuine intraday candles and retain source/freshness metadata."""
    encoded = requests.utils.quote(symbol.strip().upper(), safe="")
    response = requests.get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}",
        params={
            "range": range_,
            "interval": interval,
            "includePrePost": "false",
            "events": "div,splits",
        },
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=timeout,
    )
    response.raise_for_status()
    chart = response.json().get("chart", {})
    if chart.get("error"):
        raise RuntimeError(str(chart["error"]))
    results = chart.get("result") or []
    if not results:
        raise RuntimeError(f"{symbol} 行情响应为空")
    result = results[0]
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    if not timestamps or not quote.get("close"):
        raise RuntimeError(f"{symbol} 没有可用的分时成交数据")

    length = len(timestamps)
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(timestamps, unit="s", utc=True),
            "open": _numeric(quote.get("open"), length),
            "high": _numeric(quote.get("high"), length),
            "low": _numeric(quote.get("low"), length),
            "close": _numeric(quote.get("close"), length),
            "volume": _numeric(quote.get("volume"), length),
        }
    ).dropna(subset=["timestamp", "close"])
    frame = frame.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    if frame.empty:
        raise RuntimeError(f"{symbol} 没有有效价格")

    meta = result.get("meta") or {}
    observed_at = now or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    frame.attrs.update(
        {
            "symbol": symbol.strip().upper(),
            "source": INTRADAY_SOURCE,
            "fetched_at": observed_at.astimezone(timezone.utc).isoformat(timespec="seconds"),
            "currency": meta.get("currency"),
            "exchange_name": meta.get("exchangeName"),
            "exchange_timezone": meta.get("exchangeTimezoneName") or "UTC",
            "previous_close": meta.get("chartPreviousClose") or meta.get("regularMarketPreviousClose"),
            "regular_market_price": meta.get("regularMarketPrice"),
            "data_granularity": meta.get("dataGranularity") or interval,
        }
    )
    return frame


def _rsi(close: pd.Series, window: int = 14) -> pd.Series:
    change = close.diff()
    gain = change.clip(lower=0).ewm(alpha=1 / window, adjust=False).mean()
    loss = (-change.clip(upper=0)).ewm(alpha=1 / window, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    value = 100 - 100 / (1 + rs)
    value = value.mask((loss == 0) & (gain > 0), 100.0)
    return value.mask((loss == 0) & (gain == 0), 50.0)


def _return_over_bars(close: pd.Series, bars: int) -> float:
    if len(close) <= bars:
        return np.nan
    base = close.iloc[-bars - 1]
    return float(close.iloc[-1] / base - 1) if pd.notna(base) and base != 0 else np.nan


def _market_is_open(calendar_name: str, now: datetime) -> bool:
    try:
        import exchange_calendars as xcals

        calendar = xcals.get_calendar(calendar_name)
        minute = pd.Timestamp(now).tz_convert("UTC").floor("min")
        return bool(calendar.is_open_on_minute(minute, ignore_breaks=False))
    except Exception:
        return False


def _battle_label(score: float) -> str:
    if score >= 25:
        return "多方占优"
    if score >= 8:
        return "多方略占优"
    if score > -8:
        return "多空胶着"
    if score > -25:
        return "空方略占优"
    return "空方占优"


def analyze_intraday(
    frame: pd.DataFrame,
    *,
    name: str,
    calendar_name: str,
    now: datetime | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Turn one-minute OHLCV into an explainable, descriptive bull/bear score."""
    if frame.empty:
        raise ValueError("分时行情为空")
    data = frame.copy().sort_values("timestamp").drop_duplicates("timestamp")
    attrs = dict(frame.attrs)
    for column in ("open", "high", "low", "close", "volume"):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna(subset=["close"])
    close = data["close"]
    data["ema5"] = close.ewm(span=5, adjust=False).mean()
    data["ema20"] = close.ewm(span=20, adjust=False).mean()
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    data["macd_hist"] = macd - signal
    data["rsi14"] = _rsi(close)

    usable_volume = data["volume"].fillna(0).clip(lower=0)
    typical = data[["high", "low", "close"]].mean(axis=1).fillna(close)
    cumulative_volume = usable_volume.cumsum()
    data["vwap"] = (typical * usable_volume).cumsum() / cumulative_volume.replace(0, np.nan)
    candle_range = (data["high"] - data["low"]).abs().replace(0, np.nan)
    direction = ((data["close"] - data["open"]) / candle_range).clip(-1, 1).fillna(0)
    data["signed_volume"] = direction * usable_volume

    latest = data.iloc[-1]
    previous_close = pd.to_numeric(pd.Series([attrs.get("previous_close")]), errors="coerce").iloc[0]
    session_return = float(latest.close / previous_close - 1) if pd.notna(previous_close) and previous_close else np.nan
    return_5m = _return_over_bars(close, 5)
    return_15m = _return_over_bars(close, 15)
    return_60m = _return_over_bars(close, 60)
    prior_volume = usable_volume.iloc[-25:-5]
    recent_volume = usable_volume.tail(5)
    volume_ratio = (
        float(recent_volume.mean() / prior_volume.mean())
        if len(prior_volume) >= 5 and prior_volume.mean() > 0
        else np.nan
    )
    flow_volume = float(usable_volume.tail(30).sum())
    pressure = float(data["signed_volume"].tail(30).sum() / flow_volume) if flow_volume > 0 else np.nan

    components: list[dict[str, Any]] = []

    def add_component(label: str, signal_value: float, weight: float, evidence: str) -> None:
        if pd.notna(signal_value):
            components.append(
                {"indicator": label, "signal": float(np.clip(signal_value, -1, 1)), "weight": weight, "evidence": evidence}
            )

    if pd.notna(latest.vwap) and latest.vwap:
        distance = float(latest.close / latest.vwap - 1)
        add_component("价格 / VWAP", np.tanh(distance / 0.0025), 20, f"偏离 {distance:+.2%}")
    ema_spread = float(latest.ema5 / latest.ema20 - 1) if latest.ema20 else np.nan
    add_component("EMA5 / EMA20", np.tanh(ema_spread / 0.0015), 20, f"乖离 {ema_spread:+.2%}")
    if pd.notna(return_5m):
        add_component("5分钟动量", np.tanh(return_5m / 0.003), 15, f"涨跌 {return_5m:+.2%}")
    macd_scale = max(float(close.tail(30).std()), abs(float(latest.close)) * 0.0005)
    add_component("MACD柱", np.tanh(float(latest.macd_hist) / macd_scale), 15, f"柱值 {latest.macd_hist:+.4g}")
    if pd.notna(latest.rsi14):
        add_component("RSI14", (float(latest.rsi14) - 50) / 25, 10, f"RSI {latest.rsi14:.1f}")
    if pd.notna(pressure):
        add_component("30分钟量价压力", pressure * 2, 20, f"压力 {pressure:+.1%}")

    available_weight = sum(item["weight"] for item in components)
    score = (
        sum(item["signal"] * item["weight"] for item in components) / available_weight * 100
        if available_weight
        else 0.0
    )
    for item in components:
        item["contribution"] = item["signal"] * item["weight"] / available_weight * 100

    observed_at = now or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    else:
        observed_at = observed_at.astimezone(timezone.utc)
    last_timestamp = pd.Timestamp(data.timestamp.iloc[-1]).to_pydatetime()
    if last_timestamp.tzinfo is None:
        last_timestamp = last_timestamp.replace(tzinfo=timezone.utc)
    delay_seconds = max(0, int((observed_at - last_timestamp).total_seconds()))
    market_open = _market_is_open(calendar_name, observed_at)
    if market_open:
        freshness = "近实时" if delay_seconds <= 180 else "延迟" if delay_seconds <= 1200 else "陈旧"
        session_state = "交易中"
    else:
        freshness = "最近收盘数据"
        session_state = "休市/已收盘"

    timezone_name = str(attrs.get("exchange_timezone") or "UTC")
    try:
        local_timestamp = pd.Timestamp(last_timestamp).tz_convert(timezone_name)
    except Exception:
        local_timestamp = pd.Timestamp(last_timestamp)
    quality = min(1.0, len(data) / 60) * (available_weight / 100)
    summary = {
        "name": name,
        "symbol": attrs.get("symbol"),
        "currency": attrs.get("currency"),
        "last": float(latest.close),
        "session_open": float(data.open.dropna().iloc[0]) if data.open.notna().any() else np.nan,
        "session_high": float(data.high.max()) if data.high.notna().any() else np.nan,
        "session_low": float(data.low.min()) if data.low.notna().any() else np.nan,
        "session_volume": float(usable_volume.sum()) if usable_volume.sum() > 0 else np.nan,
        "previous_close": float(previous_close) if pd.notna(previous_close) else np.nan,
        "session_return": session_return,
        "return_5m": return_5m,
        "return_15m": return_15m,
        "return_60m": return_60m,
        "vwap": float(latest.vwap) if pd.notna(latest.vwap) else np.nan,
        "rsi14": float(latest.rsi14) if pd.notna(latest.rsi14) else np.nan,
        "volume_ratio": volume_ratio,
        "pressure": pressure,
        "score": round(float(score), 1),
        "label": _battle_label(score),
        "session_state": session_state,
        "freshness": freshness,
        "delay_seconds": delay_seconds,
        "last_timestamp": local_timestamp.isoformat(),
        "exchange_timezone": timezone_name,
        "bars": len(data),
        "quality": float(quality),
        "source": attrs.get("source", INTRADAY_SOURCE),
        "components": pd.DataFrame(components),
    }
    data.attrs.update(attrs)
    return data, summary


def fetch_semiconductor_battle(
    *, now: datetime | None = None, max_workers: int = 4
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], dict[str, str]]:
    """Fetch and analyze all four battlefields concurrently; failures stay explicit."""
    frames: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}
    summaries: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(fetch_intraday, config["symbol"], now=now): (name, config)
            for name, config in SEMICONDUCTOR_MARKETS.items()
        }
        for future in as_completed(futures):
            name, config = futures[future]
            try:
                raw = future.result()
                analyzed, summary = analyze_intraday(
                    raw, name=name, calendar_name=config["calendar"], now=now
                )
                frames[name] = analyzed
                summaries.append({key: value for key, value in summary.items() if key != "components"})
                frames[name].attrs["components"] = summary["components"]
            except Exception as error:
                errors[name] = f"{type(error).__name__}: {error}"
    summary_frame = pd.DataFrame(summaries)
    if not summary_frame.empty:
        order = {name: index for index, name in enumerate(SEMICONDUCTOR_MARKETS)}
        summary_frame["_order"] = summary_frame["name"].map(order)
        summary_frame = summary_frame.sort_values("_order").drop(columns="_order").reset_index(drop=True)
    return summary_frame, frames, errors


def aggregate_battle(summary: pd.DataFrame) -> dict[str, Any]:
    """Equal-weight available instruments; expose coverage instead of filling failures."""
    if summary.empty:
        return {"score": np.nan, "label": "暂无数据", "coverage": 0, "bulls": 0, "bears": 0}
    score = float(pd.to_numeric(summary["score"], errors="coerce").mean())
    return {
        "score": round(score, 1),
        "label": _battle_label(score),
        "coverage": len(summary),
        "bulls": int((summary["score"] >= 8).sum()),
        "bears": int((summary["score"] <= -8).sum()),
    }
