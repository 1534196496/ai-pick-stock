from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from stock_picker.market_radar import (
    breadth,
    fetch_radar_group,
    normalized_curves,
    parse_custom_symbols,
    summarize_intraday,
)


def frame(direction: int = 1, volume: bool = True) -> pd.DataFrame:
    close = 100 + direction * np.linspace(0.1, 2, 40)
    result = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-08-20 13:30", periods=40, freq="min", tz="UTC"),
            "open": close - direction * 0.05,
            "high": close + 0.1,
            "low": close - 0.1,
            "close": close,
            "volume": 1000 if volume else np.nan,
        }
    )
    result.attrs.update(
        {
            "symbol": "TEST", "currency": "USD", "previous_close": 100,
            "exchange_timezone": "America/New_York", "source": "fixture",
        }
    )
    return result


def test_custom_symbol_parser_is_ordered_deduplicated_and_bounded():
    assert parse_custom_symbols("spy, QQQ；spy 000300.ss") == ["SPY", "QQQ", "000300.SS"]
    assert len(parse_custom_symbols(" ".join(f"A{i}" for i in range(20)))) == 12
    with pytest.raises(ValueError):
        parse_custom_symbols("SPY;https://example.com")


def test_flow_proxy_is_explicit_and_directional():
    bullish = summarize_intraday(frame(1), "上涨")
    bearish = summarize_intraday(frame(-1), "下跌")
    assert bullish["flow_proxy"] > 0
    assert bearish["flow_proxy"] < 0
    assert bullish["flow_kind"] == "最近30分钟量价成交额代理"


def test_missing_volume_never_becomes_fake_fund_flow():
    summary = summarize_intraday(frame(1, volume=False), "指数")
    assert pd.isna(summary["flow_proxy"])
    assert pd.isna(summary["flow_strength"])
    assert summary["flow_kind"] == "无可靠成交量"


def test_group_fetch_keeps_partial_failure_visible(monkeypatch):
    def fake_fetch(symbol, now=None):
        if symbol == "BAD":
            raise RuntimeError("fixture failure")
        result = frame()
        result.attrs["symbol"] = symbol
        return result

    monkeypatch.setattr("stock_picker.market_radar.fetch_intraday", fake_fetch)
    summary, frames, errors = fetch_radar_group({"成功":"GOOD", "失败":"BAD"}, now=datetime.now(timezone.utc))
    assert summary.symbol.tolist() == ["GOOD"]
    assert "成功" in frames
    assert "失败" in errors


def test_breadth_and_normalized_curves_use_available_rows_only():
    summary = pd.DataFrame(
        {
            "name": ["A", "B", "C"], "session_return": [0.01, -0.02, 0.0],
            "previous_close": [100, 100, 100],
        }
    )
    result = breadth(summary)
    assert result == {"advances": 1, "declines": 1, "flat": 1, "average_return": pytest.approx(-0.01 / 3)}
    curves = normalized_curves(summary, {"A":frame(1), "B":frame(-1)})
    assert curves.columns.tolist() == ["A", "B"]
