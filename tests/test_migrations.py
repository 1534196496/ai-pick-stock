import sqlite3

from stock_picker.db import Database


def test_legacy_lineage_is_marked_and_schema_versioned(tmp_path):
    path = tmp_path / "legacy.db"
    con = sqlite3.connect(path)
    con.executescript("""
    CREATE TABLE daily_prices(code TEXT, trade_date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL, amount REAL, PRIMARY KEY(code,trade_date));
    INSERT INTO daily_prices VALUES ('000001','2025-01-01',1,1,1,1,1,1);
    CREATE TABLE snapshots(code TEXT, snapshot_date TEXT, pe REAL, pb REAL, market_cap REAL, amount REAL, pct_change REAL, PRIMARY KEY(code,snapshot_date));
    """)
    con.commit(); con.close()
    db = Database(path)
    row = db.query_df("SELECT source, fetched_at, adjustment FROM daily_prices").iloc[0]
    assert row.source == row.fetched_at == row.adjustment == "legacy_unknown"
    versions = db.query_df("SELECT version FROM schema_migrations ORDER BY version")["version"].tolist()
    assert versions == list(range(1, 10))
