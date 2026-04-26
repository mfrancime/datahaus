#!/usr/bin/env python3
"""Migrate DuckDB from Phase 1 schema to Phase 2.

Adds exchange column, backfills existing rows as 'binance',
recreates table with new PK (exchange, open_time).
Idempotent — safe to run multiple times.
"""

from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "warehouse" / "datahaus.duckdb"
SCHEMA_SQL = PROJECT_ROOT / "warehouse" / "schema.sql"


def main() -> None:
    con = duckdb.connect(str(DB_PATH))
    try:
        cols = [c[0] for c in con.execute("DESCRIBE curated.btc_ohlcv").fetchall()]

        if "exchange" in cols:
            count = con.execute("SELECT COUNT(*) FROM curated.btc_ohlcv").fetchone()[0]
            print(f"Schema already has exchange column — no migration needed. ({count} rows)")
            return

        print("Adding exchange column and migrating...")
        con.execute("ALTER TABLE curated.btc_ohlcv ADD COLUMN exchange VARCHAR")
        con.execute("UPDATE curated.btc_ohlcv SET exchange = 'binance'")
        con.execute("ALTER TABLE curated.btc_ohlcv ALTER COLUMN exchange SET NOT NULL")
        con.execute("ALTER TABLE curated.btc_ohlcv ADD COLUMN confirm BOOLEAN")
        print("Migration step 1: columns added, existing rows tagged as binance.")

        # Recreate table with new PK
        print("Recreating table with new PK (exchange, open_time)...")
        con.execute("CREATE TABLE curated.btc_ohlcv_backup AS SELECT * FROM curated.btc_ohlcv")
        con.execute("DROP TABLE curated.btc_ohlcv")

        schema_ddl = SCHEMA_SQL.read_text()
        for stmt in schema_ddl.split(";"):
            s = stmt.strip()
            if s:
                con.execute(s)

        con.execute(
            """INSERT INTO curated.btc_ohlcv
               SELECT exchange, open_time, open, high, low, close, volume,
                      close_time, quote_volume, trade_count,
                      taker_buy_base_volume, taker_buy_quote_volume,
                      confirm, ingested_at
               FROM curated.btc_ohlcv_backup"""
        )
        con.execute("DROP TABLE curated.btc_ohlcv_backup")

        count = con.execute("SELECT COUNT(*) FROM curated.btc_ohlcv").fetchone()[0]
        print(f"Migration complete. {count} rows preserved with PK (exchange, open_time).")
    except duckdb.CatalogException:
        print("Table curated.btc_ohlcv does not exist. Run 'make db-init' first.")
    finally:
        con.close()


if __name__ == "__main__":
    main()
