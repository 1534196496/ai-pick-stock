import pandas as pd

from stock_picker.analysis import (
    fund_summary,
    fund_technical_indicators,
    stock_technical_indicators,
)


def test_stock_diagnosis_has_expected_technical_indicators():
    dates = pd.bdate_range("2025-01-01", periods=300)
    close = pd.Series([10 + index * 0.02 for index in range(300)])
    frame = pd.DataFrame(
        {
            "trade_date": dates,
            "open": close - 0.05,
            "high": close + 0.1,
            "low": close - 0.1,
            "close": close,
            "volume": [1_000_000 + index * 100 for index in range(300)],
        }
    )
    technical, metrics = stock_technical_indicators(frame)
    assert {"ma20", "ma60", "ma120", "macd_hist", "rsi14", "boll_upper", "atr14", "volume_ratio"}.issubset(technical.columns)
    assert 0 <= metrics["rsi14"] <= 100
    assert metrics["ma20"] > metrics["ma60"] > metrics["ma120"]


def test_fund_diagnosis_uses_cumulative_nav_for_risk_metrics():
    frame = pd.DataFrame(
        {"date": pd.bdate_range("2025-01-01", periods=300), "nav": [1 + index / 1000 for index in range(300)]}
    )
    frame["drawdown"] = frame.nav / frame.nav.cummax() - 1
    frame.attrs["nav_kind"] = "累计净值"
    technical = fund_technical_indicators(frame)
    summary = fund_summary(frame)
    assert {"ma20", "ma60", "ma120", "rolling_volatility_60d", "drawdown"}.issubset(technical.columns)
    assert summary["total_return_compatible"]
    assert pd.notna(summary["sharpe"])
