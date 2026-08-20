from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd

from .analysis import cached_fund_history
from .db import Database
from .events import refresh_fomc_events, seed_official_events
from .global_screen import GLOBAL_EQUITY_UNIVERSE
from .multi_asset import MARKET_GROUPS, cached_asset_history, cached_treasury_yield_curve


def sync_multi_asset_data(db: Database, workers: int = 6) -> dict:
    """Refresh global prices, user funds, Treasury curve and event cache."""
    symbols = {symbol for group in MARKET_GROUPS.values() for symbol in group.values()}
    symbols.update(GLOBAL_EQUITY_UNIVERSE)
    user_assets = db.query_df("""
        SELECT code AS symbol, asset_type FROM watchlist
        UNION SELECT symbol, asset_type FROM holdings
        UNION SELECT symbol, asset_type FROM transactions
    """)
    fund_codes = set()
    for row in user_assets.itertuples():
        if row.asset_type == "fund":
            fund_codes.add(str(row.symbol)[-6:].zfill(6))
        elif row.asset_type not in {"a_share", "cash", "stock"}:
            symbols.add(str(row.symbol).upper())
    failures: list[str] = []
    succeeded = 0

    def refresh_symbol(symbol: str) -> None:
        frame, _ = cached_asset_history(db, symbol, refresh=True, period="2y")
        if frame.empty:
            raise RuntimeError("empty price history")

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {executor.submit(refresh_symbol, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            try:
                future.result(); succeeded += 1
            except Exception as error:
                failures.append(f"{futures[future]}: {type(error).__name__}")
    for code in sorted(fund_codes):
        try:
            if cached_fund_history(db, code, refresh=True).empty:
                raise RuntimeError("empty fund NAV")
            succeeded += 1
        except Exception as error:
            failures.append(f"fund:{code}: {type(error).__name__}")
    try:
        curve = cached_treasury_yield_curve(db, refresh=True)
        if curve.empty:
            raise RuntimeError("empty Treasury curve")
        succeeded += 1
    except Exception as error:
        failures.append(f"UST_curve: {type(error).__name__}")
    seed_official_events(db)
    try:
        refresh_fomc_events(db)
        succeeded += 1
    except Exception as error:
        failures.append(f"FOMC_calendar: {type(error).__name__}")
    return {"succeeded": succeeded, "failed": len(failures), "failures": failures, "symbols": len(symbols), "funds": len(fund_codes)}
