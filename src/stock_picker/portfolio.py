from __future__ import annotations

from datetime import datetime

import pandas as pd

from .db import Database
from .analysis import cached_fund_history, stock_history
from .multi_asset import asset_metadata, cached_asset_history


FX_TO_CNY = {
    "USD": "USDCNY=X", "HKD": "HKDCNY=X", "JPY": "JPYCNY=X",
    "EUR": "EURCNY=X", "GBP": "GBPCNY=X", "AUD": "AUDCNY=X",
    "CAD": "CADCNY=X", "CHF": "CHFCNY=X",
}


def add_holding(db: Database, symbol: str, name: str, asset_type: str, quantity: float, cost_price: float, currency: str, account: str = "", note: str = "", contract_multiplier: float = 1.0) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    normalized_symbol = symbol.strip().upper()
    if asset_type == "a_share":
        normalized_symbol = normalized_symbol.replace(".SS", "").replace(".SZ", "")[-6:].zfill(6)
    elif asset_type == "fund":
        normalized_symbol = normalized_symbol[-6:].zfill(6)
    with db.connect() as con:
        con.execute(
            "INSERT INTO holdings(symbol,name,asset_type,quantity,cost_price,currency,account,note,created_at,updated_at,contract_multiplier) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (normalized_symbol, name.strip() or normalized_symbol, asset_type, quantity, cost_price, currency.upper(), account.strip(), note.strip(), now, now, contract_multiplier),
        )


def delete_holding(db: Database, holding_id: int) -> None:
    with db.connect() as con:
        con.execute("DELETE FROM holdings WHERE holding_id=?", (holding_id,))


def list_holdings(db: Database) -> pd.DataFrame:
    return db.query_df("SELECT * FROM holdings ORDER BY updated_at DESC")


def value_holdings(db: Database, refresh: bool = False) -> pd.DataFrame:
    holdings = list_holdings(db)
    if holdings.empty:
        return holdings
    rows = []
    for row in holdings.itertuples():
        item = row._asdict()
        if row.asset_type == "cash":
            normalized_currency = row.currency
            if normalized_currency == "CNY":
                fx_rate = 1.0
            elif normalized_currency in FX_TO_CNY:
                try:
                    fx_history, _ = cached_asset_history(db, FX_TO_CNY[normalized_currency], refresh=refresh, period="1mo")
                    fx_rate = float(fx_history.close.iloc[-1]) if not fx_history.empty else None
                except Exception:
                    fx_rate = None
            else:
                fx_rate = None
            item.update({
                "latest_price": 1.0, "price_date": datetime.now().date().isoformat(), "source": "用户录入现金余额",
                "market_value": row.quantity, "pnl": 0.0, "pnl_pct": 0.0,
                "quote_currency": row.currency, "currency_mismatch": False, "fx_to_cny": fx_rate,
                "market_value_cny": row.quantity * fx_rate if fx_rate is not None else None,
                "cost_value_cny": row.quantity * fx_rate if fx_rate is not None else None,
            })
            rows.append(item)
            continue
        try:
            if row.asset_type == "a_share":
                history = stock_history(db, row.symbol, refresh=refresh)
                item["latest_price"] = float(history.close.iloc[-1]) if not history.empty else None
                item["price_date"] = history.trade_date.max().strftime("%Y-%m-%d") if not history.empty else None
                item["source"] = str(history.iloc[-1].get("source") or "AKShare / 本地A股缓存") if not history.empty else None
                quote_currency = "CNY"
            elif row.asset_type == "fund":
                history = cached_fund_history(
                    db, row.symbol, refresh=refresh, purpose="valuation"
                )
                item["latest_price"] = float(history.nav.iloc[-1]) if not history.empty else None
                item["price_date"] = history.date.max().strftime("%Y-%m-%d") if not history.empty else None
                item["source"] = f"AKShare / 东方财富{history.attrs.get('nav_kind', '基金净值')}" if not history.empty else None
                quote_currency = "CNY"
            else:
                history, source = cached_asset_history(db, row.symbol, refresh=refresh, period="1y")
                item["latest_price"] = float(history.close.iloc[-1]) if not history.empty else None
                item["price_date"] = history.date.max().strftime("%Y-%m-%d") if not history.empty else None
                item["source"] = source
                meta = asset_metadata(db, row.symbol)
                quote_currency = meta.get("currency") or row.currency
            multiplier = float(getattr(row, "contract_multiplier", 1.0))
            item["market_value"] = item["latest_price"] * row.quantity * multiplier if item["latest_price"] is not None else None
            item["quote_currency"] = quote_currency
            item["currency_mismatch"] = bool(quote_currency and quote_currency != row.currency)
            unit_scale = 0.01 if quote_currency in {"GBp", "GBX"} else 1.0
            normalized_currency = "GBP" if quote_currency in {"GBp", "GBX"} else quote_currency
            normalized_cost_currency = "GBP" if row.currency in {"GBp", "GBX"} else row.currency
            if normalized_currency == normalized_cost_currency:
                item["pnl"] = (item["latest_price"] * unit_scale - row.cost_price) * row.quantity * multiplier
                item["pnl_pct"] = item["latest_price"] * unit_scale / row.cost_price - 1 if row.cost_price else None
            else:
                # Cost-date FX is not stored. Refuse to show an invalid P&L.
                item["pnl"] = None
                item["pnl_pct"] = None
            if normalized_currency == "CNY":
                fx_rate = 1.0
            elif normalized_currency in FX_TO_CNY:
                fx_history, _ = cached_asset_history(db, FX_TO_CNY[normalized_currency], refresh=refresh, period="1mo")
                fx_rate = float(fx_history.close.iloc[-1]) if not fx_history.empty else None
            else:
                fx_rate = None
            item["fx_to_cny"] = fx_rate
            item["market_value_cny"] = item["market_value"] * unit_scale * fx_rate if item["market_value"] is not None and fx_rate is not None else None
            item["cost_value_cny"] = row.cost_price * row.quantity * multiplier * fx_rate if fx_rate is not None and normalized_currency == normalized_cost_currency else None
        except Exception:
            item.update({"latest_price": None, "price_date": None, "source": None, "market_value": None, "pnl": None, "pnl_pct": None, "quote_currency": row.currency, "currency_mismatch": False, "fx_to_cny": None, "market_value_cny": None, "cost_value_cny": None})
        rows.append(item)
    frame = pd.DataFrame(rows)
    total = frame["market_value_cny"].sum(min_count=1)
    frame["weight"] = frame["market_value_cny"] / total if pd.notna(total) and total else None
    return frame


def portfolio_risk_summary(frame: pd.DataFrame) -> dict:
    if frame.empty or frame["market_value_cny"].isna().any():
        return {"complete": False}
    total = float(frame["market_value_cny"].sum())
    weights = frame["market_value_cny"] / total if total else pd.Series(dtype=float)
    by_asset = frame.groupby("asset_type")["market_value_cny"].sum().sort_values(ascending=False) / total
    by_currency = frame.groupby("quote_currency")["market_value_cny"].sum().sort_values(ascending=False) / total
    return {
        "complete": True,
        "total_cny": total,
        "largest_weight": float(weights.max()) if not weights.empty else 0,
        "effective_count": float(1 / (weights.pow(2).sum())) if not weights.empty and weights.pow(2).sum() else 0,
        "asset_exposure": by_asset,
        "currency_exposure": by_currency,
    }


def save_investor_profile(db: Database, horizon_years: int, max_drawdown_pct: float, liquidity_months: int, base_currency: str, objective: str) -> None:
    with db.connect() as con:
        con.execute(
            """INSERT INTO investor_profile VALUES (1,?,?,?,?,?,?)
            ON CONFLICT(profile_id) DO UPDATE SET horizon_years=excluded.horizon_years,
            max_drawdown_pct=excluded.max_drawdown_pct, liquidity_months=excluded.liquidity_months,
            base_currency=excluded.base_currency, objective=excluded.objective, updated_at=excluded.updated_at""",
            (horizon_years, max_drawdown_pct, liquidity_months, base_currency, objective, datetime.now().isoformat(timespec="seconds")),
        )


def get_investor_profile(db: Database) -> dict | None:
    frame = db.query_df("SELECT * FROM investor_profile WHERE profile_id=1")
    return frame.iloc[0].to_dict() if not frame.empty else None


def holding_return_matrix(db: Database) -> pd.DataFrame:
    """Daily adjusted returns converted to CNY; used for correlation, not forecasts."""
    holdings = list_holdings(db)
    series = {}
    for row in holdings.itertuples():
        if row.asset_type == "cash":
            continue
        try:
            if row.asset_type == "a_share":
                history = stock_history(db, row.symbol)
                prices = history.set_index("trade_date")["close"].sort_index()
                currency = "CNY"
            elif row.asset_type == "fund":
                history = cached_fund_history(db, row.symbol, purpose="analysis")
                prices = history.set_index("date")["nav"].sort_index()
                currency = "CNY"
            else:
                history, _ = cached_asset_history(db, row.symbol, period="2y")
                if history.empty:
                    continue
                prices = history.set_index("date")["close"].sort_index()
                meta = asset_metadata(db, row.symbol)
                currency = meta.get("currency") or row.currency
            scale = 0.01 if currency in {"GBp", "GBX"} else 1.0
            currency = "GBP" if currency in {"GBp", "GBX"} else currency
            if currency != "CNY":
                fx_symbol = FX_TO_CNY.get(currency)
                if not fx_symbol:
                    continue
                fx, _ = cached_asset_history(db, fx_symbol, period="2y")
                fx_prices = fx.set_index("date")["close"].reindex(prices.index).ffill().bfill()
                prices = prices * fx_prices * scale
            series[row.symbol] = prices.pct_change()
        except Exception:
            continue
    return pd.DataFrame(series).dropna(how="all")


def stress_portfolio(frame: pd.DataFrame, shocks: dict[str, float]) -> dict:
    if frame.empty or frame["market_value_cny"].isna().any():
        return {"complete": False}
    shocked = frame.copy()
    shocked["assumed_shock"] = shocked["asset_type"].map(shocks).fillna(0.0)
    shocked["estimated_change_cny"] = shocked["market_value_cny"] * shocked["assumed_shock"]
    total = float(shocked["market_value_cny"].sum())
    change = float(shocked["estimated_change_cny"].sum())
    return {"complete": True, "change_cny": change, "change_pct": change / total if total else 0, "details": shocked}


def add_transaction(db: Database, symbol: str, asset_type: str, trade_date: str, side: str, quantity: float, price: float, fees: float, currency: str, fx_to_cny: float | None, note: str = "", account: str = "") -> None:
    with db.connect() as con:
        con.execute(
            """INSERT INTO transactions(symbol,asset_type,trade_date,side,quantity,price,fees,currency,fx_to_cny,note,created_at,account)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (symbol.strip().upper(), asset_type, trade_date, side, quantity, price, fees, currency, fx_to_cny, note.strip(), datetime.now().isoformat(timespec="seconds"), account.strip()),
        )


def list_transactions(db: Database) -> pd.DataFrame:
    return db.query_df("SELECT * FROM transactions ORDER BY trade_date DESC, transaction_id DESC")


def delete_transaction(db: Database, transaction_id: int) -> None:
    with db.connect() as con:
        con.execute("DELETE FROM transactions WHERE transaction_id=?", (transaction_id,))


def transaction_ledger_summary(db: Database) -> pd.DataFrame:
    """Average-cost ledger in CNY using the user-entered trade-date FX."""
    transactions = db.query_df("SELECT * FROM transactions ORDER BY trade_date, transaction_id")
    if transactions.empty:
        return pd.DataFrame()
    books: dict[str, dict] = {}
    for row in transactions.itertuples():
        account = str(getattr(row, "account", "") or "")
        key = (row.symbol, account, row.currency)
        book = books.setdefault(key, {
            "symbol": row.symbol, "account": account, "currency": row.currency,
            "asset_type": row.asset_type, "net_quantity": 0.0,
            "cost_basis_cny": 0.0, "realized_pnl_cny": 0.0, "income_cny": 0.0,
            "quality_status": "ok",
        })
        fx = float(row.fx_to_cny) if row.fx_to_cny is not None and row.fx_to_cny > 0 else None
        if fx is None:
            book["quality_status"] = "missing_trade_fx"
            continue
        quantity, price, fees = float(row.quantity), float(row.price), float(row.fees)
        if row.side == "buy":
            book["net_quantity"] += quantity
            book["cost_basis_cny"] += (quantity * price + fees) * fx
        elif row.side == "sell":
            if quantity > book["net_quantity"] + 1e-9:
                book["quality_status"] = "sell_exceeds_recorded_position"
                continue
            average_cost = book["cost_basis_cny"] / book["net_quantity"] if book["net_quantity"] else 0.0
            book["realized_pnl_cny"] += (quantity * price - fees) * fx - quantity * average_cost
            book["cost_basis_cny"] -= quantity * average_cost
            book["net_quantity"] -= quantity
        elif row.side == "dividend":
            book["income_cny"] += (quantity * price - fees) * fx
        elif row.side == "fee":
            book["income_cny"] -= (price + fees) * fx
    frame = pd.DataFrame(books.values())
    frame["average_cost_cny"] = frame.cost_basis_cny.div(frame.net_quantity.replace(0, pd.NA))
    return frame.sort_values("symbol").reset_index(drop=True)


def save_target_allocations(db: Database, targets: dict[str, float]) -> None:
    if abs(sum(targets.values()) - 1.0) > 0.001:
        raise ValueError("目标权重之和必须为100%")
    now = datetime.now().isoformat(timespec="seconds")
    with db.connect() as con:
        con.execute("DELETE FROM target_allocations")
        con.executemany("INSERT INTO target_allocations VALUES (?,?,?)", [(key, value, now) for key, value in targets.items() if value > 0])


def allocation_drift(db: Database, valued: pd.DataFrame) -> pd.DataFrame:
    targets = db.query_df("SELECT asset_type, target_weight FROM target_allocations")
    if targets.empty or valued.empty or valued["market_value_cny"].isna().any():
        return pd.DataFrame()
    total = valued.market_value_cny.sum()
    current = valued.groupby("asset_type").market_value_cny.sum().div(total).rename("current_weight")
    frame = targets.set_index("asset_type").join(current, how="outer").fillna(0).reset_index()
    frame["drift"] = frame.current_weight - frame.target_weight
    return frame
