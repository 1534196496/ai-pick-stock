from datetime import datetime, timezone

import numpy as np
import pandas as pd

from stock_picker.semiconductor_battle import (
    SEMICONDUCTOR_MARKETS,
    aggregate_battle,
    analyze_intraday,
    fetch_intraday,
)


def test_hynix_uses_nasdaq_adr_not_korean_listing():
    assert SEMICONDUCTOR_MARKETS["SK海力士 ADR"] == {
        "symbol": "SKHY", "currency": "USD", "calendar": "XNYS"
    }


def intraday_frame(direction: int = 1, count: int = 80) -> pd.DataFrame:
    close = 100 + direction * np.linspace(0.1, 4, count)
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-08-20 13:30", periods=count, freq="min", tz="UTC"),
            "open": close - direction * 0.08,
            "high": close + 0.12,
            "low": close - 0.12,
            "close": close,
            "volume": np.linspace(1000, 2500, count),
        }
    )
    frame.attrs.update(
        {
            "symbol": "TEST",
            "previous_close": 100,
            "currency": "USD",
            "exchange_timezone": "America/New_York",
            "source": "fixture",
        }
    )
    return frame


def test_fetch_intraday_preserves_real_metadata(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "chart": {
                    "result": [
                        {
                            "timestamp": [1_700_000_000, 1_700_000_060],
                            "meta": {
                                "currency": "USD",
                                "exchangeName": "NMS",
                                "exchangeTimezoneName": "America/New_York",
                                "chartPreviousClose": 99.5,
                            },
                            "indicators": {
                                "quote": [
                                    {
                                        "open": [100, 101], "high": [102, 103],
                                        "low": [99, 100], "close": [101, 102],
                                        "volume": [1000, 1500],
                                    }
                                ]
                            },
                        }
                    ],
                    "error": None,
                }
            }

    monkeypatch.setattr("stock_picker.semiconductor_battle.requests.get", lambda *args, **kwargs: Response())
    frame = fetch_intraday("MU", now=datetime(2026, 8, 20, tzinfo=timezone.utc))
    assert frame.close.tolist() == [101, 102]
    assert frame.attrs["symbol"] == "MU"
    assert frame.attrs["previous_close"] == 99.5
    assert frame.attrs["exchange_timezone"] == "America/New_York"


def test_bullish_and_bearish_tape_score_in_expected_direction(monkeypatch):
    monkeypatch.setattr("stock_picker.semiconductor_battle._market_is_open", lambda *args: True)
    now = datetime(2026, 8, 20, 14, 50, tzinfo=timezone.utc)
    _, bullish = analyze_intraday(intraday_frame(1), name="多头样本", calendar_name="XNYS", now=now)
    _, bearish = analyze_intraday(intraday_frame(-1), name="空头样本", calendar_name="XNYS", now=now)
    assert bullish["score"] >= 25
    assert bullish["label"] == "多方占优"
    assert bearish["score"] <= -25
    assert bearish["label"] == "空方占优"
    assert bullish["pressure"] > 0
    assert bearish["pressure"] < 0


def test_missing_volume_does_not_invent_flow_pressure(monkeypatch):
    monkeypatch.setattr("stock_picker.semiconductor_battle._market_is_open", lambda *args: False)
    frame = intraday_frame(1)
    frame["volume"] = np.nan
    _, summary = analyze_intraday(
        frame, name="指数样本", calendar_name="XNYS", now=datetime(2026, 8, 21, tzinfo=timezone.utc)
    )
    assert pd.isna(summary["pressure"])
    assert "30分钟量价压力" not in summary["components"]["indicator"].tolist()
    assert summary["quality"] < 1
    assert summary["freshness"] == "最近收盘数据"


def test_aggregate_reports_partial_coverage_without_filling_failures():
    summary = pd.DataFrame({"score": [30.0, -10.0]})
    result = aggregate_battle(summary)
    assert result["score"] == 10.0
    assert result["coverage"] == 2
    assert result["bulls"] == 1
    assert result["bears"] == 1
