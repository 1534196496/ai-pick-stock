from __future__ import annotations

from datetime import datetime

import pandas as pd

from .db import Database


def list_watchlist(db: Database, asset_type: str | None = None) -> pd.DataFrame:
    if asset_type:
        return db.query_df(
            "SELECT * FROM watchlist WHERE asset_type=? ORDER BY updated_at DESC",
            (asset_type,),
        )
    return db.query_df("SELECT * FROM watchlist ORDER BY updated_at DESC")


def save_watchlist_item(
    db: Database,
    code: str,
    name: str,
    asset_type: str = "stock",
    thesis: str = "",
    risk_note: str = "",
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with db.connect() as con:
        con.execute(
            """INSERT INTO watchlist VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(code, asset_type) DO UPDATE SET name=excluded.name,
            thesis=excluded.thesis, risk_note=excluded.risk_note,
            updated_at=excluded.updated_at""",
            (code.strip(), asset_type, name.strip() or code.strip(), thesis.strip(), risk_note.strip(), now, now),
        )


def remove_watchlist_item(db: Database, code: str, asset_type: str = "stock") -> None:
    with db.connect() as con:
        con.execute("DELETE FROM watchlist WHERE code=? AND asset_type=?", (code, asset_type))


def add_note(db: Database, code: str, note: str, asset_type: str = "stock") -> None:
    if not note.strip():
        return
    with db.connect() as con:
        con.execute(
            "INSERT INTO research_notes(code, asset_type, note, created_at) VALUES (?, ?, ?, ?)",
            (code.strip(), asset_type, note.strip(), datetime.now().isoformat(timespec="seconds")),
        )


def list_notes(db: Database, code: str, asset_type: str = "stock") -> pd.DataFrame:
    return db.query_df(
        "SELECT note_id, note, created_at FROM research_notes WHERE code=? AND asset_type=? ORDER BY created_at DESC",
        (code, asset_type),
    )


def delete_note(db: Database, note_id: int) -> None:
    with db.connect() as con:
        con.execute("DELETE FROM research_notes WHERE note_id=?", (note_id,))
