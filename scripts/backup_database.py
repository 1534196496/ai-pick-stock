"""Create or restore a consistent SQLite backup using SQLite's backup API."""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sqlite3
import os
import shutil


def backup(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(source)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst)
        result = dst.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"备份完整性检查失败: {result}")
    finally:
        dst.close()
        src.close()


def restore(source: Path, destination: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(source)
    try:
        if src.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("备份文件完整性检查失败")
        temporary = destination.with_suffix(destination.suffix + ".restore.tmp")
        temporary.unlink(missing_ok=True)
        dst = sqlite3.connect(temporary)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    if destination.exists():
        safety = destination.with_name(destination.stem + f".before-restore-{datetime.now():%Y%m%d%H%M%S}" + destination.suffix)
        backup(destination, safety)
    try:
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["backup", "restore"])
    parser.add_argument("--source")
    parser.add_argument("--destination")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.action == "backup":
        source = Path(args.source) if args.source else root / "data" / "stocks.db"
        destination = Path(args.destination) if args.destination else root / "backups" / f"stocks-{datetime.now():%Y%m%d-%H%M%S}.db"
        backup(source, destination)
        print(destination)
    else:
        if not args.source:
            parser.error("restore 必须提供 --source 备份文件")
        destination = Path(args.destination) if args.destination else root / "data" / "stocks.db"
        restore(Path(args.source), destination)
        print(destination)


if __name__ == "__main__":
    main()
