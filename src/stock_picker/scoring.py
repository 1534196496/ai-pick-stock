from __future__ import annotations

import numpy as np
import pandas as pd


METRICS = [
    "return_20d", "return_60d", "return_120d", "volatility_20d",
    "max_drawdown_120d", "avg_amount_20d", "positive_weeks", "pe", "pb",
]


def _pct_rank(series: pd.Series, higher_is_better: bool = True) -> pd.Series:
    clean = series.replace([np.inf, -np.inf], np.nan)
    ranked = clean.rank(pct=True, ascending=higher_is_better)
    return ranked.fillna(0.25)


def calculate_features(prices: pd.DataFrame, snapshots: pd.DataFrame, min_days: int = 150) -> pd.DataFrame:
    rows: list[dict] = []
    for code, group in prices.groupby("code"):
        group = group.sort_values("trade_date").drop_duplicates("trade_date").tail(260)
        if len(group) < min_days:
            continue
        close = group["close"].astype(float)
        returns = close.pct_change()
        trailing = close.tail(120)
        drawdown = trailing / trailing.cummax() - 1
        weekly_returns = close.groupby(np.arange(len(close)) // 5).last().pct_change().tail(24)
        rows.append({
            "code": code,
            "close": close.iloc[-1],
            "return_20d": close.iloc[-1] / close.iloc[-21] - 1,
            "return_60d": close.iloc[-1] / close.iloc[-61] - 1,
            "return_120d": close.iloc[-1] / close.iloc[-121] - 1,
            "volatility_20d": returns.tail(20).std() * np.sqrt(252),
            "max_drawdown_120d": drawdown.min(),
            "avg_amount_20d": group["amount"].tail(20).mean(),
            "positive_weeks": (weekly_returns > 0).mean(),
            "above_ma60": float(close.iloc[-1] > close.tail(60).mean()),
        })
    features = pd.DataFrame(rows)
    if features.empty:
        return features
    latest = snapshots.sort_values("snapshot_date").drop_duplicates("code", keep="last")
    return features.merge(latest[["code", "pe", "pb"]], on="code", how="left")


def score_stocks(features: pd.DataFrame, weights: dict[str, float], max_pe: float, max_pb: float) -> pd.DataFrame:
    if features.empty:
        return features
    frame = features.copy()
    frame = frame[
        frame["pe"].between(0, max_pe, inclusive="both")
        & (frame["max_drawdown_120d"] >= -0.40)
        & (frame["volatility_20d"] <= 0.80)
    ].copy()
    if frame.empty:
        return frame
    momentum = (
        0.25 * _pct_rank(frame["return_20d"])
        + 0.35 * _pct_rank(frame["return_60d"])
        + 0.25 * _pct_rank(frame["return_120d"])
        + 0.15 * frame["above_ma60"]
    )
    risk = 0.55 * _pct_rank(frame["volatility_20d"], False) + 0.45 * _pct_rank(frame["max_drawdown_120d"])
    valid_pe = frame["pe"]
    valid_pb = frame["pb"].where(frame["pb"].between(0, max_pb))
    valuation = 0.6 * _pct_rank(valid_pe, False) + 0.4 * _pct_rank(valid_pb, False) if valid_pb.notna().mean() >= 0.5 else _pct_rank(valid_pe, False)
    liquidity = _pct_rank(frame["avg_amount_20d"])
    stability = _pct_rank(frame["positive_weeks"])
    frame["score"] = 100 * (
        weights["momentum"] * momentum
        + weights["risk"] * risk
        + weights["valuation"] * valuation
        + weights["liquidity"] * liquidity
        + weights["stability"] * stability
    )
    frame["reasons"] = frame.apply(_reasons, axis=1)
    return frame.sort_values(["score", "avg_amount_20d"], ascending=False).reset_index(drop=True)


def _reasons(row: pd.Series) -> str:
    reasons = []
    if row["return_60d"] > 0 and row["above_ma60"]:
        reasons.append("中期趋势向上")
    if row["volatility_20d"] < 0.35:
        reasons.append("近期波动较低")
    if row["max_drawdown_120d"] > -0.20:
        reasons.append("近120日回撤受控")
    if pd.notna(row["pe"]) and 0 < row["pe"] < 30:
        reasons.append("市盈率相对温和")
    if row["positive_weeks"] >= 0.55:
        reasons.append("上涨周占比较高")
    return "；".join(reasons) or "综合因子排名靠前"
