from datetime import date

import pandas as pd

from stock_picker.db import Database
from stock_picker.recommendations import (
    FUND_CATEGORIES,
    _shrunk_rank,
    analyze_fund_batch,
    analyze_stock_batch,
    formal_recommendation_trail,
    sync_full_fund_universe,
    sync_full_stock_universe,
)


def test_thin_section_percentiles_are_shrunk_toward_neutral():
    singleton = _shrunk_rank(pd.Series([10.0]))
    larger = _shrunk_rank(pd.Series(range(20)))
    assert singleton.iloc[0] == 0.6
    assert larger.max() > singleton.iloc[0]
    assert larger.max() < 1.0


def test_formal_trail_excludes_invalid_runs(tmp_path):
    db = Database(tmp_path / "trail.db")
    with db.connect() as con:
        for run_id, status, created_at in [
            ("valid", "complete", "2026-08-14T18:00:00"),
            ("invalid", "invalid", "2026-08-15T18:00:00"),
        ]:
            con.execute(
                """INSERT INTO recommendation_runs(
                run_id,universe_batch_id,asset_type,market,as_of_date,created_at,status,
                model_version,universe_count,eligible_count,section_count,published_count,message
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, "batch", "stock", "A股", created_at[:10], created_at, status,
                 "fixture", 1, 1, 1, 1, "fixture"),
            )
            con.execute(
                """INSERT INTO recommendation_scores(
                run_id,asset_type,section,code,name,rank,score,confidence,eligible,recommended,
                last_value,return_3m,return_1y,risk_metric,data_as_of,reasons,risks,exclusion_reason,source
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, "stock", "测试", "600000", "测试股票", 1, 80, 100, 1, 1,
                 10, 0.1, 0.2, -0.1, created_at[:10], "fixture", "fixture", None, "fixture"),
            )
    trail = formal_recommendation_trail(db, "stock", "600000")
    assert trail.run_id.tolist() == ["valid"]


def test_stock_recommendations_are_versioned_and_capped_at_five(tmp_path):
    db = Database(tmp_path / "stock-rec.db")
    codes = [f"6000{i:02d}" for i in range(6)]
    spot = pd.DataFrame(
        {
            "code": codes,
            "name": [f"测试公司{i}" for i in range(6)],
            "last_price": [10 + i for i in range(6)],
            "amount": [2e8 + i * 1e7 for i in range(6)],
            "market_cap": [1e10] * 6,
            "pe": [15 + i for i in range(6)],
            "pb": [2.0] * 6,
            "pct_change": [0.0] * 6,
        }
    )
    financials = pd.DataFrame(
        {
            "code": codes,
            "raw_sector": ["软件服务"] * 6,
            "roe": [12 + i for i in range(6)],
            "revenue_growth": [8 + i for i in range(6)],
            "profit_growth": [7 + i for i in range(6)],
            "operating_cashflow_per_share": [1.0] * 6,
            "gross_margin": [35.0] * 6,
            "announcement_date": ["2026-04-20"] * 6,
        }
    )
    batch = sync_full_stock_universe(db, spot, financials)
    dates = pd.bdate_range(end="2026-08-14", periods=200)
    for offset, code in enumerate(codes):
        prices = pd.DataFrame(
            {
                "code": code,
                "trade_date": dates.strftime("%Y-%m-%d"),
                "open": [10 + offset + i * 0.02 for i in range(200)],
                "high": [10.2 + offset + i * 0.02 for i in range(200)],
                "low": [9.8 + offset + i * 0.02 for i in range(200)],
                "close": [10 + offset + i * 0.02 for i in range(200)],
                "volume": [1e6] * 200,
                "amount": [2e8] * 200,
            }
        )
        db.upsert_prices(prices, "fixture", "qfq")
    db.upsert_prices(
        pd.DataFrame(
            [{
                "code": codes[0], "trade_date": "2026-08-17", "open": 999,
                "high": 999, "low": 999, "close": 999, "volume": 1e6, "amount": 2e8,
            }]
        ),
        "future-fixture",
        "qfq",
    )
    first = analyze_stock_batch(db, batch["batch_id"], candidates_per_section=6)
    second = analyze_stock_batch(db, batch["batch_id"], candidates_per_section=6)
    assert first["status"] == "complete"
    assert first["published"] <= 5
    assert first["run_id"] != second["run_id"]
    assert len(db.query_df("SELECT * FROM recommendation_runs")) == 2
    scored = db.query_df("SELECT data_as_of FROM recommendation_scores WHERE run_id=?", (first["run_id"],))
    batch_date = db.query_df(
        "SELECT as_of_date FROM universe_batches WHERE batch_id=?", (batch["batch_id"],)
    ).iloc[0].as_of_date
    assert (scored.data_as_of <= batch_date).all()


def _fund_category_frame(category: str, start: int) -> pd.DataFrame:
    today = date.today().isoformat()
    rows = []
    for index in range(6):
        rows.append(
            {
                "基金代码": f"{start + index:06d}", "基金简称": f"{category}测试基金{index}A",
                "日期": today, "单位净值": 1 + index / 100, "累计净值": 1.5 + index / 100,
                "近1周": 1 + index, "近1月": 2 + index, "近3月": 4 + index,
                "近6月": 6 + index, "近1年": 10 + index, "近2年": 20 + index,
                "近3年": 30 + index, "今年来": 8 + index, "成立来": 40 + index,
                "手续费": "0.15%",
            }
        )
    return pd.DataFrame(rows)


def test_fund_recommendations_keep_all_batches_and_each_category_max_five(tmp_path):
    db = Database(tmp_path / "fund-rec.db")
    frames = {category: _fund_category_frame(category, 100000 + group * 100) for group, category in enumerate(FUND_CATEGORIES)}
    batch = sync_full_fund_universe(db, frames)
    nav_dates = pd.bdate_range(end=date.today(), periods=300)
    for frame in frames.values():
        for code in frame["基金代码"]:
            nav = pd.DataFrame({"date": nav_dates, "nav": [1 + i / 1000 for i in range(300)]})
            db.upsert_fund_nav(code, nav, "累计净值", "fixture", pd.Timestamp.now(tz="Asia/Shanghai").isoformat())
    result = analyze_fund_batch(db, batch["batch_id"], candidates_per_section=6)
    sections = db.query_df("SELECT * FROM recommendation_sections WHERE run_id=?", (result["run_id"],))
    assert result["status"] == "complete"
    assert len(sections) == len(FUND_CATEGORIES)
    assert (sections.published_count <= 5).all()
    assert (sections.published_count > 0).all()


def test_unexpected_fund_history_failure_blocks_publication(tmp_path, monkeypatch):
    db = Database(tmp_path / "fund-partial.db")
    frames = {
        category: _fund_category_frame(category, 300000 + group * 100)
        for group, category in enumerate(FUND_CATEGORIES)
    }
    batch = sync_full_fund_universe(db, frames)
    dates = pd.bdate_range(end=date.today(), periods=300)

    def fake_history(_db, code, refresh=False, purpose="analysis"):
        if code == "300000":
            raise RuntimeError("upstream unavailable")
        history = pd.DataFrame({"date": dates, "nav": [1 + i / 1000 for i in range(300)]})
        history.attrs["nav_kind"] = "累计净值"
        return history

    monkeypatch.setattr("stock_picker.recommendations.cached_fund_history", fake_history)
    result = analyze_fund_batch(db, batch["batch_id"], candidates_per_section=6)
    assert result["status"] == "partial"
    assert result["published"] == 0
    assert result["failures"] == {"300000": "RuntimeError: upstream unavailable"}
