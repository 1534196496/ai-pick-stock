import pandas as pd

from stock_picker.db import Database
from stock_picker.maintenance import sync_multi_asset_data


def test_multi_asset_job_persists_macro_and_user_fund(tmp_path, monkeypatch):
    db = Database(tmp_path / "multi.db")
    now = pd.Timestamp.now().isoformat()
    with db.connect() as con:
        con.execute("INSERT INTO watchlist VALUES (?,?,?,?,?,?,?)", ("161725", "fund", "基金", "", "", now, now))
    prices = pd.DataFrame({"date": pd.to_datetime(["2026-08-13"]), "close": [100.0]})
    fund = pd.DataFrame({"date": pd.to_datetime(["2026-08-13"]), "nav": [1.5]})
    curve = pd.DataFrame({"Date": pd.to_datetime(["2026-08-13"]), "2 Yr": [3.5], "10 Yr": [4.0]})
    monkeypatch.setattr("stock_picker.maintenance.MARKET_GROUPS", {"test":{"Asset":"TEST"}})
    monkeypatch.setattr("stock_picker.maintenance.GLOBAL_EQUITY_UNIVERSE", {})
    monkeypatch.setattr("stock_picker.maintenance.cached_asset_history", lambda db, symbol, refresh, period: (prices, "fixture"))
    monkeypatch.setattr("stock_picker.maintenance.cached_fund_history", lambda db, code, refresh: fund)
    monkeypatch.setattr("stock_picker.maintenance.cached_treasury_yield_curve", lambda db, refresh: curve)
    monkeypatch.setattr("stock_picker.maintenance.seed_official_events", lambda db: None)
    monkeypatch.setattr("stock_picker.maintenance.refresh_fomc_events", lambda db: 2)
    result = sync_multi_asset_data(db, workers=1)
    assert result["failed"] == 0
    assert result["funds"] == 1
    assert result["succeeded"] == 4
