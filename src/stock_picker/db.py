from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3

import pandas as pd


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL,
  description TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS instruments (
  code TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS daily_prices (
  code TEXT NOT NULL,
  trade_date TEXT NOT NULL,
  open REAL, high REAL, low REAL, close REAL, volume REAL, amount REAL,
  PRIMARY KEY (code, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_prices_date ON daily_prices(trade_date);
CREATE TABLE IF NOT EXISTS snapshots (
  code TEXT NOT NULL,
  snapshot_date TEXT NOT NULL,
  pe REAL, pb REAL, market_cap REAL, amount REAL, pct_change REAL,
  PRIMARY KEY (code, snapshot_date)
);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  as_of_date TEXT NOT NULL,
  created_at TEXT NOT NULL,
  universe_count INTEGER NOT NULL,
  scored_count INTEGER NOT NULL,
  status TEXT NOT NULL,
  message TEXT
);
CREATE TABLE IF NOT EXISTS picks (
  run_id TEXT NOT NULL,
  rank INTEGER NOT NULL,
  code TEXT NOT NULL,
  name TEXT NOT NULL,
  score REAL NOT NULL,
  close REAL,
  pe REAL, pb REAL,
  return_20d REAL, return_60d REAL, return_120d REAL,
  volatility_20d REAL, max_drawdown_120d REAL, avg_amount_20d REAL,
  reasons TEXT,
  PRIMARY KEY (run_id, code)
);
CREATE TABLE IF NOT EXISTS events (
  event_id TEXT PRIMARY KEY,
  event_date TEXT NOT NULL,
  end_date TEXT,
  title TEXT NOT NULL,
  category TEXT NOT NULL,
  importance TEXT NOT NULL,
  region TEXT NOT NULL,
  description TEXT,
  source_url TEXT,
  reminder_days INTEGER NOT NULL DEFAULT 7,
  is_custom INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_date ON events(event_date);
CREATE TABLE IF NOT EXISTS watchlist (
  code TEXT NOT NULL,
  asset_type TEXT NOT NULL,
  name TEXT NOT NULL,
  thesis TEXT,
  risk_note TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (code, asset_type)
);
CREATE TABLE IF NOT EXISTS research_notes (
  note_id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL,
  asset_type TEXT NOT NULL,
  note TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notes_asset ON research_notes(code, asset_type, created_at);
CREATE TABLE IF NOT EXISTS asset_prices (
  symbol TEXT NOT NULL,
  price_date TEXT NOT NULL,
  open REAL, high REAL, low REAL, close REAL, volume REAL,
  source TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  price_kind TEXT NOT NULL DEFAULT 'unknown',
  PRIMARY KEY (symbol, price_date)
);
CREATE INDEX IF NOT EXISTS idx_asset_prices_date ON asset_prices(symbol, price_date);
CREATE TABLE IF NOT EXISTS asset_metadata (
  symbol TEXT PRIMARY KEY,
  currency TEXT,
  exchange_timezone TEXT,
  instrument_type TEXT,
  exchange_name TEXT,
  source TEXT NOT NULL,
  fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS holdings (
  holding_id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  name TEXT NOT NULL,
  asset_type TEXT NOT NULL,
  quantity REAL NOT NULL,
  cost_price REAL NOT NULL,
  currency TEXT NOT NULL,
  account TEXT,
  note TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_holdings_symbol ON holdings(symbol);
CREATE TABLE IF NOT EXISTS investor_profile (
  profile_id INTEGER PRIMARY KEY CHECK(profile_id=1),
  horizon_years INTEGER NOT NULL,
  max_drawdown_pct REAL NOT NULL,
  liquidity_months INTEGER NOT NULL,
  base_currency TEXT NOT NULL,
  objective TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS data_jobs (
  job_id TEXT PRIMARY KEY,
  job_type TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,
  succeeded INTEGER NOT NULL DEFAULT 0,
  failed INTEGER NOT NULL DEFAULT 0,
  message TEXT
);
CREATE TABLE IF NOT EXISTS transactions (
  transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  asset_type TEXT NOT NULL,
  trade_date TEXT NOT NULL,
  side TEXT NOT NULL CHECK(side IN ('buy','sell','dividend','fee','deposit','withdrawal')),
  quantity REAL NOT NULL DEFAULT 0,
  price REAL NOT NULL DEFAULT 0,
  fees REAL NOT NULL DEFAULT 0,
  currency TEXT NOT NULL,
  fx_to_cny REAL,
  note TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS target_allocations (
  asset_type TEXT PRIMARY KEY,
  target_weight REAL NOT NULL CHECK(target_weight >= 0 AND target_weight <= 1),
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fundamental_observations (
  symbol TEXT NOT NULL,
  field TEXT NOT NULL,
  as_of_date TEXT NOT NULL,
  value REAL,
  currency TEXT,
  source TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  PRIMARY KEY (symbol, field, as_of_date)
);
CREATE INDEX IF NOT EXISTS idx_fundamental_symbol ON fundamental_observations(symbol, as_of_date);
CREATE TABLE IF NOT EXISTS fund_nav_prices (
  code TEXT NOT NULL,
  nav_date TEXT NOT NULL,
  nav REAL NOT NULL,
  nav_kind TEXT NOT NULL,
  source TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  PRIMARY KEY (code, nav_date, nav_kind)
);
CREATE TABLE IF NOT EXISTS macro_observations (
  series_id TEXT NOT NULL,
  observation_date TEXT NOT NULL,
  value REAL,
  unit TEXT NOT NULL,
  source TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  PRIMARY KEY (series_id, observation_date)
);
CREATE TABLE IF NOT EXISTS universe_batches (
  batch_id TEXT PRIMARY KEY,
  asset_type TEXT NOT NULL,
  market TEXT NOT NULL,
  as_of_date TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,
  source TEXT NOT NULL,
  source_tier TEXT NOT NULL,
  total_count INTEGER NOT NULL DEFAULT 0,
  stored_count INTEGER NOT NULL DEFAULT 0,
  eligible_count INTEGER NOT NULL DEFAULT 0,
  failed_count INTEGER NOT NULL DEFAULT 0,
  message TEXT
);
CREATE INDEX IF NOT EXISTS idx_universe_batches_date
  ON universe_batches(as_of_date, asset_type, started_at);
CREATE TABLE IF NOT EXISTS stock_universe_snapshots (
  batch_id TEXT NOT NULL,
  code TEXT NOT NULL,
  name TEXT NOT NULL,
  market TEXT NOT NULL,
  board TEXT,
  sector TEXT,
  raw_sector TEXT,
  last_price REAL,
  pe REAL,
  pb REAL,
  market_cap REAL,
  amount REAL,
  pct_change REAL,
  roe REAL,
  revenue_growth REAL,
  profit_growth REAL,
  operating_cashflow_per_share REAL,
  gross_margin REAL,
  announcement_date TEXT,
  source TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  PRIMARY KEY (batch_id, code)
);
CREATE INDEX IF NOT EXISTS idx_stock_universe_batch_sector
  ON stock_universe_snapshots(batch_id, sector, code);
CREATE TABLE IF NOT EXISTS fund_universe_snapshots (
  batch_id TEXT NOT NULL,
  code TEXT NOT NULL,
  name TEXT NOT NULL,
  category TEXT NOT NULL,
  nav_date TEXT,
  unit_nav REAL,
  cumulative_nav REAL,
  return_1w REAL,
  return_1m REAL,
  return_3m REAL,
  return_6m REAL,
  return_1y REAL,
  return_2y REAL,
  return_3y REAL,
  return_ytd REAL,
  return_since_inception REAL,
  fee_rate REAL,
  fund_company TEXT,
  manager_names TEXT,
  manager_experience_days REAL,
  star_rating_count REAL,
  rating_score REAL,
  fund_size_cny REAL,
  inception_date TEXT,
  quality_source TEXT,
  source TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  PRIMARY KEY (batch_id, category, code)
);
CREATE INDEX IF NOT EXISTS idx_fund_universe_batch_category
  ON fund_universe_snapshots(batch_id, category, code);
CREATE TABLE IF NOT EXISTS fund_master (
  code TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  fund_type TEXT,
  source TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS recommendation_runs (
  run_id TEXT PRIMARY KEY,
  universe_batch_id TEXT NOT NULL,
  asset_type TEXT NOT NULL,
  market TEXT NOT NULL,
  as_of_date TEXT NOT NULL,
  created_at TEXT NOT NULL,
  status TEXT NOT NULL,
  model_version TEXT NOT NULL,
  universe_count INTEGER NOT NULL,
  eligible_count INTEGER NOT NULL,
  section_count INTEGER NOT NULL,
  published_count INTEGER NOT NULL,
  message TEXT,
  model_config_json TEXT,
  input_hash TEXT,
  code_hash TEXT
);
CREATE INDEX IF NOT EXISTS idx_recommendation_runs_date
  ON recommendation_runs(as_of_date, asset_type, created_at);
CREATE TABLE IF NOT EXISTS recommendation_sections (
  run_id TEXT NOT NULL,
  section TEXT NOT NULL,
  total_count INTEGER NOT NULL,
  analyzed_count INTEGER NOT NULL,
  qualified_count INTEGER NOT NULL,
  published_count INTEGER NOT NULL,
  status TEXT NOT NULL,
  message TEXT,
  PRIMARY KEY (run_id, section)
);
CREATE TABLE IF NOT EXISTS recommendation_scores (
  run_id TEXT NOT NULL,
  asset_type TEXT NOT NULL,
  section TEXT NOT NULL,
  code TEXT NOT NULL,
  name TEXT NOT NULL,
  rank INTEGER,
  score REAL,
  confidence REAL NOT NULL,
  eligible INTEGER NOT NULL,
  recommended INTEGER NOT NULL,
  last_value REAL,
  return_3m REAL,
  return_1y REAL,
  risk_metric REAL,
  data_as_of TEXT,
  reasons TEXT,
  risks TEXT,
  exclusion_reason TEXT,
  source TEXT NOT NULL,
  PRIMARY KEY (run_id, section, code)
);
CREATE INDEX IF NOT EXISTS idx_recommendation_scores_lookup
  ON recommendation_scores(run_id, asset_type, section, recommended, rank);
CREATE TABLE IF NOT EXISTS recommendation_exclusions (
  run_id TEXT NOT NULL,
  asset_type TEXT NOT NULL,
  section TEXT NOT NULL,
  code TEXT NOT NULL,
  name TEXT NOT NULL,
  stage TEXT NOT NULL,
  reason TEXT NOT NULL,
  PRIMARY KEY (run_id, code, stage)
);
CREATE INDEX IF NOT EXISTS idx_recommendation_exclusions_run
  ON recommendation_exclusions(run_id, asset_type, section, stage);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            self._migrate(connection)

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        """Small additive migrations for existing personal databases."""
        migrations = {
            "daily_prices": {
                "source": "TEXT", "fetched_at": "TEXT", "adjustment": "TEXT",
            },
            "snapshots": {"source": "TEXT", "fetched_at": "TEXT"},
            "holdings": {"contract_multiplier": "REAL NOT NULL DEFAULT 1.0"},
            "asset_prices": {"price_kind": "TEXT NOT NULL DEFAULT 'legacy_unknown'"},
            "events": {
                "event_time": "TEXT", "event_timezone": "TEXT",
                "verification_status": "TEXT NOT NULL DEFAULT 'cached_official'",
                "last_verified": "TEXT",
            },
            "transactions": {"account": "TEXT NOT NULL DEFAULT ''"},
            "stock_universe_snapshots": {"raw_sector": "TEXT"},
            "recommendation_runs": {
                "model_config_json": "TEXT", "input_hash": "TEXT", "code_hash": "TEXT",
            },
            "fund_universe_snapshots": {
                "fund_company": "TEXT", "manager_names": "TEXT",
                "manager_experience_days": "REAL", "star_rating_count": "REAL",
                "rating_score": "REAL", "fund_size_cny": "REAL",
                "inception_date": "TEXT", "quality_source": "TEXT",
            },
        }
        for table, columns in migrations.items():
            existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            for column, definition in columns.items():
                if column not in existing:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        # Existing rows predate lineage support. Mark them honestly rather than
        # leaving blank fields that look like missing writes.
        connection.execute("UPDATE daily_prices SET source='legacy_unknown' WHERE source IS NULL OR source='' ")
        connection.execute("UPDATE daily_prices SET adjustment='legacy_unknown' WHERE adjustment IS NULL OR adjustment='' ")
        connection.execute("UPDATE daily_prices SET fetched_at='legacy_unknown' WHERE fetched_at IS NULL OR fetched_at='' ")
        connection.execute("UPDATE snapshots SET source='legacy_unknown' WHERE source IS NULL OR source='' ")
        connection.execute("UPDATE snapshots SET fetched_at='legacy_unknown' WHERE fetched_at IS NULL OR fetched_at='' ")
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations VALUES (1, datetime('now'), 'base schema')"
        )
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations VALUES (2, datetime('now'), 'lineage, multi-asset, holdings and profile')"
        )
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations VALUES (3, datetime('now'), 'price kind, jobs, event verification and trading ledger')"
        )
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations VALUES (4, datetime('now'), 'fund NAV, fundamentals and macro observations')"
        )
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations VALUES (5, datetime('now'), 'full universe snapshots and versioned recommendations')"
        )
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations VALUES (6, datetime('now'), 'fund master universe and coverage audit')"
        )
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations VALUES (7, datetime('now'), 'source industry lineage for stock universe')"
        )
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations VALUES (8, datetime('now'), 'recommendation reproducibility and exclusions')"
        )
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations VALUES (9, datetime('now'), 'fund rating manager scale quality snapshot')"
        )

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def upsert_instruments(self, frame: pd.DataFrame, updated_at: str) -> None:
        rows = [(row.code, row.name, updated_at) for row in frame.itertuples()]
        with self.connect() as con:
            con.executemany(
                "INSERT INTO instruments VALUES (?, ?, ?) ON CONFLICT(code) DO UPDATE SET name=excluded.name, updated_at=excluded.updated_at",
                rows,
            )

    def upsert_prices(self, frame: pd.DataFrame, source: str = "unknown", adjustment: str = "unknown") -> None:
        columns = ["code", "trade_date", "open", "high", "low", "close", "volume", "amount"]
        fetched_at = pd.Timestamp.now().isoformat()
        rows = [(*row, source, fetched_at, adjustment) for row in frame[columns].itertuples(index=False, name=None)]
        with self.connect() as con:
            con.executemany(
                """INSERT INTO daily_prices(code,trade_date,open,high,low,close,volume,amount,source,fetched_at,adjustment)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(code, trade_date) DO UPDATE SET open=excluded.open, high=excluded.high,
                low=excluded.low, close=excluded.close, volume=excluded.volume, amount=excluded.amount,
                source=excluded.source, fetched_at=excluded.fetched_at, adjustment=excluded.adjustment""",
                rows,
            )

    def upsert_snapshots(self, frame: pd.DataFrame, snapshot_date: str, source: str = "unknown") -> None:
        fetched_at = pd.Timestamp.now().isoformat()
        rows = [
            (row.code, snapshot_date, row.pe, row.pb, row.market_cap, row.amount, row.pct_change, source, fetched_at)
            for row in frame.itertuples()
        ]
        with self.connect() as con:
            con.executemany(
                """INSERT INTO snapshots(code,snapshot_date,pe,pb,market_cap,amount,pct_change,source,fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(code, snapshot_date) DO UPDATE SET pe=excluded.pe, pb=excluded.pb,
                market_cap=excluded.market_cap, amount=excluded.amount, pct_change=excluded.pct_change,
                source=excluded.source, fetched_at=excluded.fetched_at""",
                rows,
            )

    def query_df(self, sql: str, params: tuple = ()) -> pd.DataFrame:
        with self.connect() as con:
            return pd.read_sql_query(sql, con, params=params)

    def upsert_asset_prices(self, symbol: str, frame: pd.DataFrame, source: str, fetched_at: str, price_kind: str = "adjusted_total_return_proxy") -> None:
        rows = [
            (symbol, row.date.strftime("%Y-%m-%d"), row.open, row.high, row.low, row.close, row.volume, source, fetched_at, price_kind)
            for row in frame.itertuples()
        ]
        with self.connect() as con:
            con.executemany(
                """INSERT INTO asset_prices(symbol,price_date,open,high,low,close,volume,source,fetched_at,price_kind)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, price_date) DO UPDATE SET open=excluded.open,
                high=excluded.high, low=excluded.low, close=excluded.close,
                volume=excluded.volume, source=excluded.source, fetched_at=excluded.fetched_at,
                price_kind=excluded.price_kind""",
                rows,
            )

    def upsert_asset_metadata(self, symbol: str, metadata: dict, source: str, fetched_at: str) -> None:
        with self.connect() as con:
            con.execute(
                """INSERT INTO asset_metadata VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET currency=excluded.currency,
                exchange_timezone=excluded.exchange_timezone,
                instrument_type=excluded.instrument_type, exchange_name=excluded.exchange_name,
                source=excluded.source, fetched_at=excluded.fetched_at""",
                (
                    symbol, metadata.get("currency"), metadata.get("exchangeTimezoneName"),
                    metadata.get("instrumentType"), metadata.get("exchangeName"), source, fetched_at,
                ),
            )

    def upsert_fundamentals(self, symbol: str, frame: pd.DataFrame, source: str, fetched_at: str) -> None:
        if frame.empty:
            return
        rows = [
            (symbol.upper(), row.field, str(row.date), row.value, row.currency, source, fetched_at)
            for row in frame.itertuples()
        ]
        with self.connect() as con:
            con.executemany(
                """INSERT INTO fundamental_observations(symbol,field,as_of_date,value,currency,source,fetched_at)
                VALUES (?,?,?,?,?,?,?) ON CONFLICT(symbol,field,as_of_date) DO UPDATE SET
                value=excluded.value,currency=excluded.currency,source=excluded.source,fetched_at=excluded.fetched_at""",
                rows,
            )

    def upsert_fund_nav(self, code: str, frame: pd.DataFrame, nav_kind: str, source: str, fetched_at: str) -> None:
        rows = [(code, row.date.strftime("%Y-%m-%d"), row.nav, nav_kind, source, fetched_at) for row in frame.itertuples()]
        with self.connect() as con:
            con.executemany(
                """INSERT INTO fund_nav_prices(code,nav_date,nav,nav_kind,source,fetched_at) VALUES (?,?,?,?,?,?)
                ON CONFLICT(code,nav_date,nav_kind) DO UPDATE SET nav=excluded.nav,source=excluded.source,fetched_at=excluded.fetched_at""",
                rows,
            )

    def upsert_macro_observations(self, rows: list[tuple]) -> None:
        with self.connect() as con:
            con.executemany(
                """INSERT INTO macro_observations(series_id,observation_date,value,unit,source,fetched_at)
                VALUES (?,?,?,?,?,?) ON CONFLICT(series_id,observation_date) DO UPDATE SET
                value=excluded.value,unit=excluded.unit,source=excluded.source,fetched_at=excluded.fetched_at""",
                rows,
            )
