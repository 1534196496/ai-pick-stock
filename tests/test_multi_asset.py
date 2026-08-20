from pathlib import Path

import pandas as pd

from stock_picker.db import Database
from stock_picker.multi_asset import asset_summary, cached_asset_history, market_session_lag, yahoo_chart_history


def price_frame(count=252):
    frame = pd.DataFrame({
        "date": pd.bdate_range("2025-01-01", periods=count),
        "open": range(100, 100 + count), "high": range(101, 101 + count),
        "low": range(99, 99 + count), "close": range(100, 100 + count),
        "volume": 1000,
    })
    frame["ma20"] = frame.close.rolling(20).mean()
    frame["ma60"] = frame.close.rolling(60).mean()
    frame["drawdown"] = frame.close / frame.close.cummax() - 1
    return frame


def test_one_year_summary_works_with_252_rows():
    summary = asset_summary(price_frame())
    assert pd.notna(summary["return_1y"])


def test_cache_refetches_when_period_coverage_is_short(tmp_path, monkeypatch):
    db = Database(tmp_path / "cache.db")
    short = price_frame(20)
    db.upsert_asset_prices("TEST", short, "fixture", pd.Timestamp.now().isoformat())
    full = price_frame(500)
    monkeypatch.setattr("stock_picker.multi_asset.yahoo_history", lambda symbol, period: full)
    result, source = cached_asset_history(db, "TEST", period="2y")
    assert len(result) == 500
    assert source == "Yahoo Finance client auto-adjusted"


def test_yahoo_chart_uses_adjusted_close(monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {"chart":{"result":[{"timestamp":[1_700_000_000,1_700_086_400],"meta":{"currency":"USD"},"indicators":{"quote":[{"open":[10,20],"high":[11,21],"low":[9,19],"close":[10,20],"volume":[1,2]}],"adjclose":[{"adjclose":[5,10]}]}}]}}
    monkeypatch.setattr("stock_picker.multi_asset.requests.get", lambda *args, **kwargs: Response())
    frame = yahoo_chart_history("TEST", "1y")
    assert frame.close.tolist() == [5, 10]
    assert frame.open.tolist() == [5, 10]
    assert frame.attrs["metadata"]["currency"] == "USD"


def test_empty_refresh_marks_existing_cache_stale(tmp_path, monkeypatch):
    db = Database(tmp_path / "stale.db")
    cached = price_frame(252)
    db.upsert_asset_prices("TEST", cached, "fixture", "2020-01-01T00:00:00")
    monkeypatch.setattr("stock_picker.multi_asset.yahoo_history", lambda symbol, period: pd.DataFrame())
    result, source = cached_asset_history(db, "TEST", refresh=True, period="1y")
    assert result.attrs["cache_status"] == "stale"
    assert "陈旧缓存" in source


def test_market_calendar_excludes_exchange_holiday():
    # NYSE was closed on 2026-07-03; only 2026-07-02 and 2026-07-06 are sessions.
    lag, calendar = market_session_lag(pd.Timestamp("2026-07-02").date(), pd.Timestamp("2026-07-06").date(), "NYQ")
    assert lag == 1
    assert calendar == "XNYS"


def test_global_exchange_aliases_use_real_calendars():
    for exchange, expected in [("NMS", "XNYS"), ("AMS", "XAMS"), ("LSE", "XLON")]:
        _, calendar = market_session_lag(pd.Timestamp("2026-08-10").date(), pd.Timestamp("2026-08-11").date(), exchange)
        assert calendar == expected


def test_legacy_price_rows_are_isolated(tmp_path, monkeypatch):
    db = Database(tmp_path / "legacy.db")
    old = price_frame(300)
    db.upsert_asset_prices("TEST", old, "legacy", "2020-01-01T00:00:00", "legacy_unknown")
    fresh = price_frame(252)
    fresh.attrs["price_kind"] = "adjusted_total_return_proxy"
    monkeypatch.setattr("stock_picker.multi_asset.yahoo_history", lambda symbol, period: fresh)
    result, _ = cached_asset_history(db, "TEST", period="1y")
    assert len(result) == 252
    assert db.query_df("SELECT COUNT(*) n FROM asset_prices WHERE symbol='TEST' AND price_kind='legacy_unknown'").iloc[0].n == 48
