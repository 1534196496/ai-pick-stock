import numpy as np
import pandas as pd

from stock_picker.scoring import calculate_features, score_stocks


def test_scoring_prefers_steady_trend_with_equal_valuation():
    dates = pd.bdate_range("2025-01-01", periods=180)
    rows = []
    for code, closes in {
        "000001": np.linspace(10, 15, len(dates)),
        "000002": 10 + np.sin(np.arange(len(dates)) / 2) * 2,
    }.items():
        for day, close in zip(dates, closes):
            rows.append({"code": code, "trade_date": day.strftime("%Y-%m-%d"), "close": close, "amount": 2e8})
    prices = pd.DataFrame(rows)
    snapshots = pd.DataFrame({"code": ["000001", "000002"], "snapshot_date": ["2025-09-01"] * 2, "pe": [15, 15], "pb": [2, 2]})
    features = calculate_features(prices, snapshots, min_days=150)
    weights = {"momentum": .35, "risk": .25, "valuation": .2, "liquidity": .1, "stability": .1}
    ranked = score_stocks(features, weights, 100, 20)
    assert ranked.iloc[0]["code"] == "000001"
    assert ranked["score"].between(0, 100).all()


def test_hard_gates_remove_invalid_valuation_and_extreme_risk():
    frame = pd.DataFrame([
        {"code":"OK", "pe":20, "pb":None, "return_20d":.1, "return_60d":.2, "return_120d":.3, "above_ma60":1, "volatility_20d":.3, "max_drawdown_120d":-.2, "avg_amount_20d":2e8, "positive_weeks":.6},
        {"code":"EXPENSIVE", "pe":200, "pb":1, "return_20d":.2, "return_60d":.3, "return_120d":.4, "above_ma60":1, "volatility_20d":.3, "max_drawdown_120d":-.2, "avg_amount_20d":2e8, "positive_weeks":.7},
        {"code":"RISKY", "pe":15, "pb":1, "return_20d":.3, "return_60d":.4, "return_120d":.5, "above_ma60":1, "volatility_20d":1.0, "max_drawdown_120d":-.5, "avg_amount_20d":2e8, "positive_weeks":.7},
    ])
    ranked = score_stocks(frame, {"momentum":.35,"risk":.25,"valuation":.2,"liquidity":.1,"stability":.1}, 100, 20)
    assert ranked.code.tolist() == ["OK"]
