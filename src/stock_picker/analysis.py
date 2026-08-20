from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from .db import Database
from .provider import AkshareProvider


def stock_history(db: Database, code: str, refresh: bool = False) -> pd.DataFrame:
    code = code.strip()[-6:].zfill(6)
    frame = db.query_df("SELECT * FROM daily_prices WHERE code=? ORDER BY trade_date", (code,))
    if frame.empty or refresh:
        provider = AkshareProvider()
        fetched = provider.history(code, date.today() - timedelta(days=1100), date.today(), "qfq")
        if not fetched.empty:
            db.upsert_prices(fetched, provider.last_source or "akshare_unknown", "qfq")
            frame = db.query_df("SELECT * FROM daily_prices WHERE code=? ORDER BY trade_date", (code,))
    if not frame.empty:
        frame["trade_date"] = pd.to_datetime(frame["trade_date"])
        frame["ma20"] = frame["close"].rolling(20).mean()
        frame["ma60"] = frame["close"].rolling(60).mean()
        frame["drawdown"] = frame["close"] / frame["close"].cummax() - 1
    return frame


def stock_summary(frame: pd.DataFrame) -> dict[str, float]:
    close = frame["close"]
    returns = close.pct_change()
    result = {
        "close": float(close.iloc[-1]),
        "return_20d": float(close.iloc[-1] / close.iloc[-21] - 1) if len(close) > 20 else np.nan,
        "return_60d": float(close.iloc[-1] / close.iloc[-61] - 1) if len(close) > 60 else np.nan,
        "return_1y": float(close.iloc[-1] / close.iloc[-243] - 1) if len(close) > 242 else np.nan,
        "volatility": float(returns.tail(60).std() * np.sqrt(252)),
        "max_drawdown": float(frame["drawdown"].min()),
    }
    return result


def stock_technical_indicators(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float]]:
    """Calculate descriptive indicators from persisted adjusted prices."""
    data = frame.copy().sort_values("trade_date").drop_duplicates("trade_date")
    close = pd.to_numeric(data["close"], errors="coerce")
    high = pd.to_numeric(data["high"], errors="coerce")
    low = pd.to_numeric(data["low"], errors="coerce")
    volume = pd.to_numeric(data["volume"], errors="coerce")
    for window in (20, 60, 120):
        data[f"ma{window}"] = close.rolling(window).mean()
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    data["macd_dif"] = ema12 - ema26
    data["macd_dea"] = data["macd_dif"].ewm(span=9, adjust=False).mean()
    data["macd_hist"] = 2 * (data["macd_dif"] - data["macd_dea"])
    change = close.diff()
    gain = change.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-change.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    data["rsi14"] = 100 - 100 / (1 + rs)
    data.loc[(loss == 0) & (gain > 0), "rsi14"] = 100.0
    data.loc[(loss == 0) & (gain == 0), "rsi14"] = 50.0
    std20 = close.rolling(20).std()
    data["boll_mid"] = data["ma20"]
    data["boll_upper"] = data["ma20"] + 2 * std20
    data["boll_lower"] = data["ma20"] - 2 * std20
    previous_close = close.shift(1)
    true_range = pd.concat(
        [(high - low), (high - previous_close).abs(), (low - previous_close).abs()], axis=1
    ).max(axis=1)
    data["atr14"] = true_range.rolling(14).mean()
    data["volume_ma20"] = volume.rolling(20).mean()
    data["volume_ratio"] = volume / data["volume_ma20"].replace(0, np.nan)
    latest = data.iloc[-1]
    high_52w = close.tail(252).max()
    metrics = {
        "ma20": float(latest["ma20"]), "ma60": float(latest["ma60"]),
        "ma120": float(latest["ma120"]), "macd_dif": float(latest["macd_dif"]),
        "macd_dea": float(latest["macd_dea"]), "macd_hist": float(latest["macd_hist"]),
        "rsi14": float(latest["rsi14"]), "atr14": float(latest["atr14"]),
        "boll_upper": float(latest["boll_upper"]), "boll_lower": float(latest["boll_lower"]),
        "volume_ratio": float(latest["volume_ratio"]),
        "distance_52w_high": float(close.iloc[-1] / high_52w - 1) if pd.notna(high_52w) else np.nan,
    }
    return data, metrics


def stock_health(summary: dict[str, float], frame: pd.DataFrame) -> dict[str, str]:
    """Translate raw metrics into neutral research labels, never trade advice."""
    close = frame["close"].iloc[-1]
    ma60 = frame["ma60"].iloc[-1]
    trend = "偏强" if pd.notna(ma60) and close > ma60 and summary["return_60d"] > 0 else "偏弱"
    volatility = summary["volatility"]
    risk = "较低" if volatility < 0.25 else "中等" if volatility < 0.45 else "较高"
    drawdown = summary["max_drawdown"]
    drawdown_label = "可控" if drawdown > -0.20 else "明显" if drawdown > -0.40 else "很深"
    return {"trend": trend, "risk": risk, "drawdown": drawdown_label}


def stock_financials(code: str) -> pd.DataFrame:
    import akshare as ak

    try:
        raw = ak.stock_financial_analysis_indicator(symbol=code, start_year=str(date.today().year - 5))
        if raw.empty:
            return raw
        raw = raw.copy()
        raw.columns = [str(column) for column in raw.columns]
        return raw.head(12)
    except Exception:
        return pd.DataFrame()


def fund_rank(category: str = "全部") -> pd.DataFrame:
    import akshare as ak

    raw = ak.fund_open_fund_rank_em(symbol=category)
    if raw.empty:
        return raw
    return raw.replace("---", np.nan)


def _legacy_fund_history(code: str) -> pd.DataFrame:
    import akshare as ak

    try:
        raw = ak.fund_open_fund_info_em(symbol=code.strip(), indicator="累计净值走势", period="成立来")
        nav_kind = "累计净值"
    except Exception:
        raw = ak.fund_open_fund_info_em(symbol=code.strip(), indicator="单位净值走势", period="成立来")
        nav_kind = "单位净值"
    if raw.empty:
        return raw
    date_col = next((c for c in raw.columns if "净值日期" in str(c) or str(c) == "日期"), raw.columns[0])
    value_col = next((c for c in raw.columns if nav_kind in str(c)), raw.columns[1])
    frame = pd.DataFrame({"date": pd.to_datetime(raw[date_col]), "nav": pd.to_numeric(raw[value_col], errors="coerce")})
    frame = frame.dropna().sort_values("date")
    frame["drawdown"] = frame["nav"] / frame["nav"].cummax() - 1
    frame.attrs["nav_kind"] = nav_kind
    return frame


def _legacy_cached_fund_history(db: Database, code: str, refresh: bool = False) -> pd.DataFrame:
    code = code.strip()[-6:].zfill(6)
    cached = db.query_df("SELECT * FROM fund_nav_prices WHERE code=? ORDER BY nav_date", (code,))
    fetched = pd.to_datetime(cached.fetched_at, errors="coerce").max() if not cached.empty else pd.NaT
    cache_today = pd.notna(fetched) and fetched.date() == date.today()
    refresh_error = None
    if refresh or cached.empty or not cache_today:
        try:
            fresh = fund_history(code)
            if fresh.empty:
                raise RuntimeError("基金净值接口返回空数据")
            nav_kind = fresh.attrs.get("nav_kind", "未知净值")
            db.upsert_fund_nav(code, fresh, nav_kind, "AKShare / 东方财富基金净值", pd.Timestamp.now(tz="Asia/Shanghai").isoformat())
            cached = db.query_df("SELECT * FROM fund_nav_prices WHERE code=? AND nav_kind=? ORDER BY nav_date", (code, nav_kind))
        except Exception as error:
            refresh_error = type(error).__name__
            if cached.empty:
                raise
    if cached.empty:
        return pd.DataFrame()
    latest_kind = "累计净值" if (cached.nav_kind == "累计净值").any() else str(cached.iloc[-1].nav_kind)
    same_kind = cached[cached.nav_kind == latest_kind]
    frame = pd.DataFrame({"date": pd.to_datetime(same_kind.nav_date), "nav": same_kind.nav})
    frame["drawdown"] = frame.nav / frame.nav.cummax() - 1
    frame.attrs["nav_kind"] = latest_kind
    frame.attrs["cache_status"] = "stale" if refresh_error else "fresh"
    frame.attrs["refresh_error"] = refresh_error
    return frame


FUND_NAV_SOURCE = "AKShare / 东方财富基金净值"


def _fetch_fund_nav(code: str, nav_kind: str) -> pd.DataFrame:
    """Fetch one explicit NAV series so valuation and total return never mix."""
    import akshare as ak

    if nav_kind not in {"单位净值", "累计净值"}:
        raise ValueError(f"不支持的净值口径: {nav_kind}")
    raw = ak.fund_open_fund_info_em(
        symbol=code.strip()[-6:].zfill(6),
        indicator=f"{nav_kind}走势",
        period="成立来",
    )
    if raw.empty:
        return pd.DataFrame()
    date_col = next(
        (column for column in raw.columns if "净值日期" in str(column) or str(column) == "日期"),
        raw.columns[0],
    )
    value_col = next((column for column in raw.columns if nav_kind in str(column)), raw.columns[1])
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(raw[date_col], errors="coerce"),
            "nav": pd.to_numeric(raw[value_col], errors="coerce"),
        }
    ).dropna()
    frame = frame.sort_values("date").drop_duplicates("date", keep="last")
    frame["drawdown"] = frame["nav"] / frame["nav"].cummax() - 1
    frame.attrs["nav_kind"] = nav_kind
    return frame


def fund_history(code: str) -> pd.DataFrame:
    """Return a total-return-compatible series when available."""
    try:
        cumulative = _fetch_fund_nav(code, "累计净值")
        if not cumulative.empty:
            return cumulative
    except Exception:
        pass
    return _fetch_fund_nav(code, "单位净值")


def cached_fund_history(
    db: Database,
    code: str,
    refresh: bool = False,
    purpose: str = "analysis",
    allow_network: bool = True,
) -> pd.DataFrame:
    """Read an explicit NAV kind.

    ``analysis`` prefers cumulative NAV for dividend-aware performance.
    ``valuation`` requires unit NAV because fund units are valued at unit NAV.
    """
    if purpose not in {"analysis", "valuation"}:
        raise ValueError("purpose 必须是 analysis 或 valuation")
    code = code.strip()[-6:].zfill(6)
    desired_kind = "单位净值" if purpose == "valuation" else "累计净值"
    all_cached = db.query_df(
        "SELECT * FROM fund_nav_prices WHERE code=? ORDER BY nav_date", (code,)
    )

    def select_kind(nav_kind: str) -> pd.DataFrame:
        if all_cached.empty:
            return pd.DataFrame()
        return all_cached[all_cached["nav_kind"] == nav_kind].copy()

    desired_cached = select_kind(desired_kind)
    fetched_at = (
        pd.to_datetime(desired_cached["fetched_at"], errors="coerce", utc=True).max()
        if not desired_cached.empty
        else pd.NaT
    )
    cache_today = pd.notna(fetched_at) and fetched_at.tz_convert("Asia/Shanghai").date() == date.today()
    errors: dict[str, str] = {}
    should_refresh = allow_network and (refresh or desired_cached.empty or not cache_today)
    if should_refresh:
        kinds = ("单位净值", "累计净值") if refresh else (desired_kind,)
        for nav_kind in kinds:
            try:
                fresh = _fetch_fund_nav(code, nav_kind)
                if fresh.empty:
                    raise RuntimeError("基金净值接口返回空数据")
                db.upsert_fund_nav(
                    code,
                    fresh,
                    nav_kind,
                    FUND_NAV_SOURCE,
                    pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
                )
            except Exception as error:
                errors[nav_kind] = f"{type(error).__name__}: {error}"
        all_cached = db.query_df(
            "SELECT * FROM fund_nav_prices WHERE code=? ORDER BY nav_date", (code,)
        )
        desired_cached = select_kind(desired_kind)

    selected_kind = desired_kind
    selected = desired_cached
    if selected.empty and purpose == "analysis":
        selected_kind = "单位净值"
        selected = select_kind(selected_kind)
    if selected.empty:
        detail = errors.get(desired_kind, "本地没有对应口径的净值")
        raise RuntimeError(f"{code} 无法取得{desired_kind}: {detail}")

    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(selected["nav_date"], errors="coerce"),
            "nav": pd.to_numeric(selected["nav"], errors="coerce"),
        }
    ).dropna().sort_values("date")
    frame["drawdown"] = frame["nav"] / frame["nav"].cummax() - 1
    frame.attrs["nav_kind"] = selected_kind
    frame.attrs["cache_status"] = "stale" if desired_kind in errors else "fresh"
    frame.attrs["refresh_error"] = errors.get(desired_kind)
    frame.attrs["source"] = FUND_NAV_SOURCE
    return frame


def fund_summary(frame: pd.DataFrame) -> dict[str, float]:
    nav = frame["nav"]
    total_return_compatible = frame.attrs.get("nav_kind") == "累计净值"
    returns = nav.pct_change()
    periods_per_year = 250
    one_year = np.nan
    if total_return_compatible and len(frame) >= 200:
        target = frame.date.iloc[-1] - pd.DateOffset(years=1)
        base = frame.loc[frame.date <= target, "nav"]
        if not base.empty:
            one_year = float(nav.iloc[-1] / base.iloc[-1] - 1)
    downside = returns.where(returns < 0).tail(250).std() * np.sqrt(periods_per_year)
    annual_return = returns.tail(250).mean() * periods_per_year
    return {
        "nav": float(nav.iloc[-1]),
        "return_1y": one_year,
        "annualized_volatility": float(returns.tail(250).std() * np.sqrt(periods_per_year)) if total_return_compatible else np.nan,
        "max_drawdown": float(frame["drawdown"].min()) if total_return_compatible else np.nan,
        "sharpe": float(annual_return / (returns.tail(250).std() * np.sqrt(periods_per_year))) if total_return_compatible and returns.tail(250).std() > 0 else np.nan,
        "sortino": float(annual_return / downside) if total_return_compatible and pd.notna(downside) and downside > 0 else np.nan,
        "downside_volatility": float(downside) if total_return_compatible else np.nan,
        "total_return_compatible": total_return_compatible,
    }


def fund_technical_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy().sort_values("date").drop_duplicates("date")
    nav = pd.to_numeric(data["nav"], errors="coerce")
    for window in (20, 60, 120, 250):
        data[f"ma{window}"] = nav.rolling(window).mean()
    data["return_20d"] = nav.pct_change(20)
    data["return_60d"] = nav.pct_change(60)
    data["rolling_volatility_60d"] = nav.pct_change().rolling(60).std() * np.sqrt(250)
    data["drawdown"] = nav / nav.cummax() - 1
    return data


def fund_profile(code: str) -> dict[str, pd.DataFrame]:
    """Public fund metadata; each section fails independently and stays absent."""
    import akshare as ak
    code = code.strip()[-6:].zfill(6)
    calls = {
        "基本资料": lambda: ak.fund_individual_basic_info_xq(symbol=code, timeout=20),
        "业绩与基准": lambda: ak.fund_individual_achievement_xq(symbol=code, timeout=20),
        "运作费用": lambda: ak.fund_fee_em(symbol=code, indicator="运作费用"),
        "最新持仓": lambda: ak.fund_portfolio_hold_em(symbol=code, date=""),
    }
    result = {}
    for name, call in calls.items():
        try:
            frame = call()
            if isinstance(frame, pd.DataFrame) and not frame.empty:
                result[name] = frame
        except Exception:
            continue
    return result
