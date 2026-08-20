import pandas as pd

from stock_picker.analysis import cached_fund_history, fund_summary
from stock_picker.db import Database


def test_unit_nav_refuses_total_return_metrics():
    frame = pd.DataFrame({"date": pd.date_range("2025-01-01", periods=300), "nav": [1 + i / 1000 for i in range(300)]})
    frame["drawdown"] = frame.nav / frame.nav.cummax() - 1
    frame.attrs["nav_kind"] = "单位净值"
    result = fund_summary(frame)
    assert not result["total_return_compatible"]
    assert pd.isna(result["return_1y"])
    assert pd.isna(result["annualized_volatility"])


def test_fund_cache_separates_unit_nav_from_cumulative_nav(tmp_path, monkeypatch):
    db = Database(tmp_path / "fund.db")

    def fake_fetch(code, nav_kind):
        value = 0.575 if nav_kind == "单位净值" else 2.2911
        frame = pd.DataFrame({"date": pd.to_datetime(["2026-08-14"]), "nav": [value]})
        frame["drawdown"] = 0.0
        frame.attrs["nav_kind"] = nav_kind
        return frame

    monkeypatch.setattr("stock_picker.analysis._fetch_fund_nav", fake_fetch)
    valuation = cached_fund_history(db, "161725", refresh=True, purpose="valuation")
    analysis = cached_fund_history(db, "161725", purpose="analysis")
    assert valuation.attrs["nav_kind"] == "单位净值"
    assert valuation.nav.iloc[-1] == 0.575
    assert analysis.attrs["nav_kind"] == "累计净值"
    assert analysis.nav.iloc[-1] == 2.2911
    assert set(db.query_df("SELECT DISTINCT nav_kind FROM fund_nav_prices")["nav_kind"]) == {"单位净值", "累计净值"}


def test_fund_cache_can_be_strictly_offline(tmp_path, monkeypatch):
    db = Database(tmp_path / "offline-fund.db")
    calls = []

    def should_not_fetch(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("offline read attempted network access")

    monkeypatch.setattr("stock_picker.analysis._fetch_fund_nav", should_not_fetch)
    try:
        cached_fund_history(db, "000406", purpose="valuation", allow_network=False)
    except RuntimeError as error:
        assert "本地没有对应口径的净值" in str(error)
    else:
        raise AssertionError("missing offline cache must be explicit")
    assert calls == []
