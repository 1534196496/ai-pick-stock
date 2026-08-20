from dataclasses import replace

import numpy as np
import pandas as pd

from stock_picker.config import load_settings
from stock_picker.db import Database
from stock_picker.pipeline import run_selection


def test_offline_database_to_report(tmp_path):
    settings = replace(
        load_settings("config.toml"),
        database=tmp_path / "stocks.db",
        reports=tmp_path / "reports",
        top_n=2,
    )
    db = Database(settings.database)
    instruments = pd.DataFrame({"code": ["000001", "600000"], "name": ["示例甲", "示例乙"]})
    db.upsert_instruments(instruments, "2026-01-01T18:30:00")
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=180)
    all_prices = []
    for code, closes in {"000001": np.linspace(10, 15, 180), "600000": np.linspace(9, 11, 180)}.items():
        all_prices.append(pd.DataFrame({
            "code": code, "trade_date": dates.strftime("%Y-%m-%d"),
            "open": closes, "high": closes * 1.01, "low": closes * .99,
            "close": closes, "volume": 1e6, "amount": 2e8,
        }))
    db.upsert_prices(pd.concat(all_prices))
    snapshot = pd.DataFrame({
        "code": ["000001", "600000"], "pe": [15.0, 12.0], "pb": [1.5, 1.2],
        "market_cap": [1e11, 9e10], "amount": [2e8, 2e8], "pct_change": [1.0, .5],
    })
    db.upsert_snapshots(snapshot, dates[-1].strftime("%Y-%m-%d"))
    picks, report = run_selection(settings)
    assert len(picks) == 2
    assert report.exists()
    assert "仅用于研究" in report.read_text(encoding="utf-8")
    assert (tmp_path / "reports" / f"{dates[-1]:%Y-%m-%d}-selection.csv").exists()
