"""Controlled live-source smoke test. Run manually; never fabricates fallback values."""
from pathlib import Path
import tempfile

from stock_picker.analysis import fund_history, stock_financials
from stock_picker.db import Database
from stock_picker.multi_asset import asset_metadata, cached_asset_history, treasury_yield_curve


def main() -> None:
    db = Database(Path(tempfile.mkdtemp(prefix="zhiheng-live-")) / "smoke.db")
    failures = []
    for symbol in ["^GSPC", "GC=F", "TLT", "0700.HK", "7203.T"]:
        try:
            frame, source = cached_asset_history(db, symbol, refresh=True, period="1y")
            meta = asset_metadata(db, symbol)
            assert len(frame) >= 200 and frame.close.notna().all()
            assert meta.get("currency") and meta.get("exchange_timezone")
            print(f"PASS {symbol}: {len(frame)} rows, {frame.date.max().date()}, {meta['currency']}, {source}")
        except Exception as error:
            failures.append(f"{symbol}: {type(error).__name__}: {error}")
    try:
        treasury = treasury_yield_curve()
        assert {"Date", "2 Yr", "10 Yr", "30 Yr"}.issubset(treasury.columns)
        print(f"PASS UST: {len(treasury)} rows, {treasury.Date.max().date()}, official CSV")
    except Exception as error:
        failures.append(f"UST: {type(error).__name__}: {error}")
    try:
        fund = fund_history("161725")
        assert len(fund) > 200 and fund.attrs.get("nav_kind") == "累计净值"
        print(f"PASS FUND 161725: {len(fund)} rows, {fund.date.max().date()}, 累计净值")
    except Exception as error:
        failures.append(f"FUND: {type(error).__name__}: {error}")
    try:
        financials = stock_financials("000001")
        assert not financials.empty and "日期" in financials.columns
        print(f"PASS A-SHARE FINANCIALS: {len(financials)} rows")
    except Exception as error:
        failures.append(f"FINANCIALS: {type(error).__name__}: {error}")
    if failures:
        raise SystemExit("LIVE SMOKE FAILED\n" + "\n".join(failures))
    print("ALL LIVE SOURCES PASSED")


if __name__ == "__main__":
    main()
