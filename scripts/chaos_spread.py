#!/usr/bin/env python3
"""Chaos injection: inject a fake price anomaly into DuckDB.

Inserts a row with a wildly different close price for a synthetic
exchange, causing the reconciliation DAG to detect a spread anomaly.

Usage:
    python chaos_spread.py           # inject anomaly
    python chaos_spread.py --clean   # remove injected rows
"""

import argparse
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WAREHOUSE_DB = PROJECT_ROOT / "warehouse" / "datahaus.duckdb"

CHAOS_EXCHANGE = "chaos_test"


def inject_anomaly() -> None:
    con = duckdb.connect(str(WAREHOUSE_DB))
    try:
        # Get the latest open_time from any exchange
        result = con.execute(
            "SELECT open_time, close FROM curated.btc_ohlcv ORDER BY open_time DESC LIMIT 1"
        ).fetchone()

        if not result:
            print("ERROR: No rows in curated.btc_ohlcv — run ingestion DAGs first.")
            return

        open_time, real_close = result
        # Inject a row with 5% higher close price to trigger spread detection
        fake_close = real_close * 1.05

        now = datetime.now(timezone.utc).isoformat()
        con.execute(
            """
            INSERT INTO curated.btc_ohlcv (
                exchange, open_time, open, high, low, close, volume,
                close_time, quote_volume, trade_count,
                taker_buy_base_volume, taker_buy_quote_volume,
                confirm, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                CHAOS_EXCHANGE,
                open_time,
                fake_close,  # open = fake close
                fake_close * 1.001,
                fake_close * 0.999,
                fake_close,  # close = 5% higher than real
                100.0,
                None, None, None, None, None, None,
                now,
            ],
        )

        print(f"CHAOS INJECTED: Fake row for exchange='{CHAOS_EXCHANGE}'")
        print(f"  open_time: {open_time}")
        print(f"  real close: {real_close:.2f}")
        print(f"  fake close: {fake_close:.2f} (+5%)")
        print("\nRun 'make run-reconciliation' to trigger spread detection.")
    finally:
        con.close()


def clean_chaos() -> None:
    con = duckdb.connect(str(WAREHOUSE_DB))
    try:
        deleted = con.execute(
            f"DELETE FROM curated.btc_ohlcv WHERE exchange = '{CHAOS_EXCHANGE}'"
        ).fetchone()
        print(f"CHAOS CLEARED: Removed all rows for exchange='{CHAOS_EXCHANGE}'.")
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Chaos: inject/clean fake price anomaly")
    parser.add_argument("--clean", action="store_true", help="Remove chaos-injected rows")
    args = parser.parse_args()

    if args.clean:
        clean_chaos()
    else:
        inject_anomaly()


if __name__ == "__main__":
    main()
