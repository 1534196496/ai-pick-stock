from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import numpy as np
import pandas as pd

from .db import Database
from .multi_asset import asset_summary, cached_asset_history, fundamental_timeseries


# A transparent, fixed liquid research universe. It is not a claim to cover
# every listed company and must not be used for historical backtests without a
# point-in-time constituent archive.
GLOBAL_EQUITY_UNIVERSE = {
    "AAPL": ("Apple", "美国"), "MSFT": ("Microsoft", "美国"),
    "GOOGL": ("Alphabet", "美国"), "AMZN": ("Amazon", "美国"),
    "META": ("Meta", "美国"),
    "JNJ": ("Johnson & Johnson", "美国"), "XOM": ("Exxon Mobil", "美国"),
    "0700.HK": ("腾讯控股", "中国香港"), "9988.HK": ("阿里巴巴-SW", "中国香港"),
    "7203.T": ("丰田汽车", "日本"), "6758.T": ("Sony", "日本"),
    "ASML.AS": ("ASML", "荷兰"), "SAP.DE": ("SAP", "德国"),
    "NESN.SW": ("Nestlé", "瑞士"), "MC.PA": ("LVMH", "法国"),
    "SHEL.L": ("Shell", "英国"), "AZN.L": ("AstraZeneca", "英国"),
    "BHP.AX": ("BHP", "澳大利亚"),
    "NVDA": ("NVIDIA", "美国"), "TSM": ("TSMC ADR", "美国"),
    "ORCL": ("Oracle", "美国"), "COST": ("Costco", "美国"),
    "HD": ("Home Depot", "美国"), "NKE": ("Nike", "美国"),
    "NVO": ("Novo Nordisk", "丹麦"), "4502.T": ("武田药品", "日本"),
    "SIE.DE": ("Siemens", "德国"), "AIR.PA": ("Airbus", "法国"),
    "7011.T": ("三菱重工", "日本"), "RIO.L": ("Rio Tinto", "英国"),
    "LIN": ("Linde", "美国"), "DTE.DE": ("Deutsche Telekom", "德国"),
    "NEE": ("NextEra Energy", "美国"), "ENEL.MI": ("Enel", "意大利"),
}

GLOBAL_EQUITY_SECTORS = {
    **{s:"科技" for s in ["AAPL","MSFT","GOOGL","META","ASML.AS","SAP.DE","NVDA","TSM","ORCL","6758.T"]},
    **{s:"消费" for s in ["AMZN","9988.HK","NESN.SW","MC.PA","7203.T","COST","HD","NKE"]},
    **{s:"医疗" for s in ["JNJ","AZN.L","NVO","4502.T"]},
    **{s:"能源材料" for s in ["XOM","SHEL.L","BHP.AX","RIO.L","LIN"]},
    **{s:"工业" for s in ["SIE.DE","AIR.PA","7011.T"]},
    **{s:"通信" for s in ["0700.HK","DTE.DE"]},
    **{s:"公用事业" for s in ["NEE","ENEL.MI"]},
}


def cached_fundamentals(db: Database, symbol: str, refresh: bool = False) -> pd.DataFrame:
    cached = db.query_df(
        "SELECT as_of_date AS date,field,value,currency,source,fetched_at FROM fundamental_observations WHERE symbol=? ORDER BY as_of_date,field",
        (symbol.upper(),),
    )
    fetched = pd.to_datetime(cached.fetched_at, errors="coerce").max() if not cached.empty else pd.NaT
    if refresh or cached.empty or pd.isna(fetched) or (pd.Timestamp.now() - fetched).days >= 1:
        fresh = fundamental_timeseries(symbol)
        if fresh.empty:
            if cached.empty:
                raise RuntimeError(f"{symbol} 没有返回基本面数据")
        else:
            fetched_at = datetime.now().astimezone().isoformat(timespec="seconds")
            db.upsert_fundamentals(symbol, fresh, "Yahoo Finance fundamentals timeseries", fetched_at)
            cached = db.query_df(
                "SELECT as_of_date AS date,field,value,currency,source,fetched_at FROM fundamental_observations WHERE symbol=? ORDER BY as_of_date,field",
                (symbol.upper(),),
            )
    return cached


def _latest(frame: pd.DataFrame, field: str) -> float:
    values = pd.to_numeric(frame.loc[frame.field == field, "value"], errors="coerce").dropna()
    return float(values.iloc[-1]) if not values.empty else np.nan


def build_global_features(symbol: str, name: str, region: str, prices: pd.DataFrame, fundamentals: pd.DataFrame) -> dict:
    summary = asset_summary(prices)
    revenue = _latest(fundamentals, "annualTotalRevenue")
    net_income = _latest(fundamentals, "annualNetIncome")
    free_cash_flow = _latest(fundamentals, "annualFreeCashFlow")
    assets = _latest(fundamentals, "annualTotalAssets")
    return {
        "symbol": symbol, "name": name, "region": region, "sector": GLOBAL_EQUITY_SECTORS.get(symbol, "其他"),
        "as_of": prices.date.max().strftime("%Y-%m-%d"),
        "pe": _latest(fundamentals, "trailingPeRatio"),
        "roa_proxy": net_income / assets if assets and assets > 0 else np.nan,
        "fcf_margin_proxy": free_cash_flow / revenue if revenue and revenue > 0 else np.nan,
        "return_1y": summary["return_1y"], "max_drawdown": summary["max_drawdown"],
    }


def score_global_features(features: pd.DataFrame) -> pd.DataFrame:
    if features.empty:
        return features
    frame = features.copy()
    required = ["pe", "roa_proxy", "fcf_margin_proxy", "return_1y", "max_drawdown"]
    for column in required:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if "sector" not in frame:
        frame["sector"] = "未分类"
    if "region" not in frame:
        frame["region"] = "未分类"
    frame = frame.dropna(subset=required)
    frame = frame[(frame.pe > 0) & (frame.pe <= 80) & (frame.roa_proxy > 0) & (frame.fcf_margin_proxy > 0) & (frame.max_drawdown > -0.65)]
    if frame.empty:
        return frame
    frame["base_score"] = (
        (1 - frame.pe.rank(pct=True)) * 0.20
        + frame.roa_proxy.rank(pct=True) * 0.20
        + frame.fcf_margin_proxy.rank(pct=True) * 0.15
        + frame.return_1y.rank(pct=True) * 0.25
        + frame.max_drawdown.rank(pct=True) * 0.20
    )
    neutral_rank = lambda series: series.rank(pct=True) if len(series) >= 3 else series
    sector_rank = frame.groupby("sector")["base_score"].transform(neutral_rank)
    region_rank = frame.groupby("region")["base_score"].transform(neutral_rank)
    frame["score"] = 100 * (frame.base_score * 0.60 + sector_rank * 0.25 + region_rank * 0.15)
    frame["evidence"] = frame.apply(
        lambda row: f"PE {row.pe:.1f}；ROA代理 {row.roa_proxy:.1%}；FCF利润率代理 {row.fcf_margin_proxy:.1%}；1年 {row.return_1y:.1%}；区间回撤 {row.max_drawdown:.1%}",
        axis=1,
    )
    return frame.sort_values("score", ascending=False).reset_index(drop=True)


def screen_global_equities(db: Database, refresh: bool = False, workers: int = 6) -> tuple[pd.DataFrame, list[str]]:
    rows: list[dict] = []
    failures: list[str] = []

    def fetch(item):
        symbol, (name, region) = item
        prices, _ = cached_asset_history(db, symbol, refresh=refresh, period="2y")
        fundamentals = cached_fundamentals(db, symbol, refresh=refresh)
        return build_global_features(symbol, name, region, prices, fundamentals)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {executor.submit(fetch, item): item[0] for item in GLOBAL_EQUITY_UNIVERSE.items()}
        for future in as_completed(futures):
            try:
                rows.append(future.result())
            except Exception as error:
                failures.append(f"{futures[future]}: {type(error).__name__}")
    return score_global_features(pd.DataFrame(rows)), failures
