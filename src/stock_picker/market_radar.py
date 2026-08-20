from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import re
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .semiconductor_battle import INTRADAY_SOURCE, fetch_intraday


REGIONS = ("中国大陆", "美国", "日本", "欧洲")

INDEX_UNIVERSES: dict[str, dict[str, str]] = {
    "中国大陆": {
        "上证指数": "000001.SS", "深证成指": "399001.SZ",
        "沪深300": "000300.SS", "中证500": "000905.SS",
    },
    "美国": {
        "标普500": "^GSPC", "纳斯达克": "^IXIC", "道琼斯": "^DJI",
        "罗素2000": "^RUT", "费城半导体": "^SOX",
    },
    "日本": {
        "日经225": "^N225", "TOPIX ETF": "1306.T", "日经225 ETF": "1321.T",
    },
    "欧洲": {
        "欧洲STOXX 600": "^STOXX", "欧元区STOXX 50": "^STOXX50E",
        "德国DAX": "^GDAXI", "英国富时100": "^FTSE", "法国CAC40": "^FCHI",
    },
}

SECTOR_UNIVERSES: dict[str, dict[str, str]] = {
    "中国大陆": {
        "半导体ETF": "512480.SS", "证券ETF": "512880.SS", "医药ETF": "512010.SS",
        "新能源车ETF": "515030.SS", "军工ETF": "512660.SS", "银行ETF": "512800.SS",
    },
    "美国": {
        "科技XLK": "XLK", "金融XLF": "XLF", "医疗XLV": "XLV",
        "可选消费XLY": "XLY", "能源XLE": "XLE", "工业XLI": "XLI",
    },
    "日本": {
        "电器精密ETF": "1625.T", "信息服务ETF": "1626.T", "银行ETF": "1631.T",
        "医药ETF": "1621.T", "汽车运输ETF": "1622.T", "能源资源ETF": "1618.T",
    },
    "欧洲": {
        "科技ETF": "EXV3.DE", "银行ETF": "EXV1.DE", "医疗ETF": "EXV4.DE",
        "工业ETF": "INDU.DE", "汽车ETF": "EXV5.DE", "能源ETF": "ENRG.PA",
    },
}

INSTRUMENT_UNIVERSES: dict[str, dict[str, str]] = {
    "中国大陆": {
        "沪深300ETF": "510300.SS", "中证500ETF": "510500.SS", "创业板ETF": "159915.SZ",
        "贵州茅台": "600519.SS", "宁德时代": "300750.SZ", "中芯国际": "688981.SS",
    },
    "美国": {
        "标普ETF SPY": "SPY", "纳指ETF QQQ": "QQQ", "半导体ETF SMH": "SMH",
        "英伟达": "NVDA", "美光": "MU", "海力士ADR": "SKHY", "闪迪": "SNDK",
    },
    "日本": {
        "TOPIX ETF": "1306.T", "日经225 ETF": "1321.T", "丰田汽车": "7203.T",
        "索尼集团": "6758.T", "软银集团": "9984.T",
    },
    "欧洲": {
        "欧洲ETF VGK": "VGK", "欧元区ETF FEZ": "FEZ", "ASML": "ASML.AS",
        "SAP": "SAP.DE", "诺和诺德": "NOVO-B.CO", "壳牌": "SHEL.L",
    },
}

_VALID_SYMBOL = re.compile(r"^[A-Z0-9^][A-Z0-9.^=_-]{0,19}$")


def parse_custom_symbols(text: str, limit: int = 12) -> list[str]:
    """Parse a small, safe Yahoo-symbol list while preserving input order."""
    values = re.split(r"[,，;；\s]+", text.upper().strip())
    result: list[str] = []
    for value in values:
        if not value or value in result:
            continue
        if not _VALID_SYMBOL.fullmatch(value):
            raise ValueError(f"无效市场代码：{value}")
        result.append(value)
        if len(result) >= limit:
            break
    return result


def _return(close: pd.Series, bars: int) -> float:
    if len(close) <= bars or close.iloc[-bars - 1] == 0:
        return np.nan
    return float(close.iloc[-1] / close.iloc[-bars - 1] - 1)


def summarize_intraday(frame: pd.DataFrame, name: str) -> dict[str, Any]:
    if frame.empty:
        raise ValueError("分时行情为空")
    data = frame.copy().sort_values("timestamp").drop_duplicates("timestamp")
    attrs = dict(frame.attrs)
    for column in ("open", "high", "low", "close", "volume"):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna(subset=["close"])
    latest = data.iloc[-1]
    previous_close = pd.to_numeric(pd.Series([attrs.get("previous_close")]), errors="coerce").iloc[0]
    session_return = float(latest.close / previous_close - 1) if pd.notna(previous_close) and previous_close else np.nan

    volume = data.volume.fillna(0).clip(lower=0)
    typical = data[["high", "low", "close"]].mean(axis=1).fillna(data.close)
    candle_range = (data.high - data.low).abs().replace(0, np.nan)
    direction = ((data.close - data.open) / candle_range).clip(-1, 1).fillna(0)
    recent = data.tail(30).index
    gross_notional = float((typical.loc[recent] * volume.loc[recent]).sum())
    signed_notional = float((typical.loc[recent] * volume.loc[recent] * direction.loc[recent]).sum())
    flow_strength = signed_notional / gross_notional if gross_notional > 0 else np.nan

    timezone_name = str(attrs.get("exchange_timezone") or "UTC")
    timestamp = pd.Timestamp(latest.timestamp)
    try:
        local_timestamp = timestamp.tz_convert(timezone_name)
    except Exception:
        local_timestamp = timestamp
    return {
        "name": name,
        "symbol": attrs.get("symbol"),
        "currency": attrs.get("currency"),
        "last": float(latest.close),
        "previous_close": float(previous_close) if pd.notna(previous_close) else np.nan,
        "session_return": session_return,
        "return_5m": _return(data.close, 5),
        "return_30m": _return(data.close, 30),
        "session_high": float(data.high.max()) if data.high.notna().any() else np.nan,
        "session_low": float(data.low.min()) if data.low.notna().any() else np.nan,
        "session_volume": float(volume.sum()) if volume.sum() > 0 else np.nan,
        "flow_proxy": signed_notional if gross_notional > 0 else np.nan,
        "flow_strength": flow_strength,
        "flow_kind": "最近30分钟量价成交额代理" if gross_notional > 0 else "无可靠成交量",
        "as_of": local_timestamp.isoformat(),
        "timezone": timezone_name,
        "bars": len(data),
        "source": attrs.get("source", INTRADAY_SOURCE),
    }


def fetch_radar_group(
    universe: Mapping[str, str], *, now: datetime | None = None, max_workers: int = 8
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], dict[str, str]]:
    """Fetch only the currently visible group; every failed symbol remains visible."""
    summaries: list[dict[str, Any]] = []
    frames: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=min(max_workers, max(1, len(universe)))) as executor:
        futures = {
            executor.submit(fetch_intraday, symbol, now=now): (name, symbol)
            for name, symbol in universe.items()
        }
        for future in as_completed(futures):
            name, _ = futures[future]
            try:
                frame = future.result()
                frames[name] = frame
                summaries.append(summarize_intraday(frame, name))
            except Exception as error:
                errors[name] = f"{type(error).__name__}: {error}"
    summary = pd.DataFrame(summaries)
    if not summary.empty:
        order = {name: index for index, name in enumerate(universe)}
        summary["_order"] = summary.name.map(order)
        summary = summary.sort_values("_order").drop(columns="_order").reset_index(drop=True)
    return summary, frames, errors


def breadth(summary: pd.DataFrame) -> dict[str, Any]:
    if summary.empty:
        return {"advances": 0, "declines": 0, "flat": 0, "average_return": np.nan}
    returns = pd.to_numeric(summary.session_return, errors="coerce")
    return {
        "advances": int((returns > 0.00005).sum()),
        "declines": int((returns < -0.00005).sum()),
        "flat": int((returns.abs() <= 0.00005).sum()),
        "average_return": float(returns.mean()),
    }


def normalized_curves(
    summary: pd.DataFrame, frames: Mapping[str, pd.DataFrame]
) -> pd.DataFrame:
    curves: dict[str, pd.Series] = {}
    for row in summary.itertuples():
        frame = frames.get(row.name)
        if frame is None or frame.empty:
            continue
        base = row.previous_close if pd.notna(row.previous_close) and row.previous_close else frame.close.iloc[0]
        curve = (pd.to_numeric(frame.close, errors="coerce").reset_index(drop=True) / base - 1) * 100
        curve.attrs = {}
        curves[row.name] = curve
    return pd.DataFrame(curves)
