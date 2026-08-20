from pathlib import Path

import pandas as pd
import pytest

from stock_picker.db import Database
from stock_picker.portfolio import add_holding, add_transaction, portfolio_risk_summary, stress_portfolio, transaction_ledger_summary, value_holdings


def test_portfolio_concentration():
    frame = pd.DataFrame({
        "asset_type": ["stock", "bond"], "quote_currency": ["USD", "CNY"],
        "market_value_cny": [600.0, 400.0],
    })
    result = portfolio_risk_summary(frame)
    assert result["complete"]
    assert result["total_cny"] == 1000
    assert result["largest_weight"] == 0.6


def test_incomplete_portfolio_refuses_total():
    frame = pd.DataFrame({"market_value_cny": [100.0, None]})
    assert not portfolio_risk_summary(frame)["complete"]


def test_stress_scenario_is_weighted_by_real_market_values():
    frame = pd.DataFrame({
        "asset_type": ["global_stock", "bond"],
        "market_value_cny": [600.0, 400.0],
    })
    result = stress_portfolio(frame, {"global_stock": -0.20, "bond": -0.05})
    assert result["complete"]
    assert result["change_cny"] == -140.0
    assert result["change_pct"] == -0.14


def test_transaction_ledger_uses_trade_date_fx(tmp_path: Path):
    db = Database(tmp_path / "ledger.db")
    add_transaction(db, "AAPL", "global_stock", "2026-01-01", "buy", 10, 100, 2, "USD", 7.0)
    add_transaction(db, "AAPL", "global_stock", "2026-02-01", "sell", 4, 120, 1, "USD", 7.1)
    add_transaction(db, "AAPL", "global_stock", "2026-03-01", "dividend", 6, 1, 0, "USD", 7.2)
    row = transaction_ledger_summary(db).iloc[0]
    assert row.net_quantity == 6
    assert row.realized_pnl_cny > 0
    assert row.income_cny == 43.2
    assert row.quality_status == "ok"


def test_a_share_and_fund_use_dedicated_pricing_routes(tmp_path: Path, monkeypatch):
    db = Database(tmp_path / "portfolio.db")
    add_holding(db, "600519.SS", "贵州茅台", "a_share", 2, 1000, "CNY")
    add_holding(db, "161725", "招商白酒", "fund", 100, 1.2, "CNY")
    stock = pd.DataFrame({"trade_date": pd.to_datetime(["2026-08-13"]), "close": [1500.0], "source": ["fixture"]})
    fund = pd.DataFrame({"date": pd.to_datetime(["2026-08-13"]), "nav": [0.575]})
    fund.attrs["nav_kind"] = "单位净值"
    purposes = []
    monkeypatch.setattr("stock_picker.portfolio.stock_history", lambda db, code, refresh=False: stock)
    monkeypatch.setattr(
        "stock_picker.portfolio.cached_fund_history",
        lambda db, code, refresh=False, purpose="analysis": purposes.append(purpose) or fund,
    )
    valued = value_holdings(db)
    assert valued.market_value_cny.notna().all()
    assert valued.loc[valued.asset_type == "fund", "market_value_cny"].iloc[0] == pytest.approx(57.5)
    assert purposes == ["valuation"]
    assert set(valued.quote_currency) == {"CNY"}
    assert db.query_df("SELECT symbol FROM holdings WHERE asset_type='a_share'").iloc[0].symbol == "600519"
