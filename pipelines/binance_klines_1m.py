"""
Binance BTC/USDT 1-minute klines ingestion pipeline.

Pulls the last 100 one-minute candles from Binance public API,
normalizes them via PySpark, and upserts into DuckDB.
Scheduled every 5 minutes for fast feedback during Phase 1.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import requests
from airflow import DAG
from airflow.operators.python import PythonOperator

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WAREHOUSE_DB = PROJECT_ROOT / "warehouse" / "datahaus.duckdb"
SCHEMA_SQL = PROJECT_ROOT / "warehouse" / "schema.sql"

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
SYMBOL = "BTCUSDT"
INTERVAL = "1m"
LIMIT = 100

default_args = {
    "owner": "datahaus",
    "retries": 3,
    "retry_delay": timedelta(minutes=1),
    "retry_exponential_backoff": True,
    "execution_timeout": timedelta(minutes=5),
}

dag = DAG(
    dag_id="binance_klines_1m",
    default_args=default_args,
    description="Ingest BTC/USDT 1m klines from Binance into DuckDB",
    schedule_interval="*/5 * * * *",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    max_active_runs=1,
    sla_miss_callback=None,
    tags=["phase-1", "crypto", "binance"],
)


def extract(**kwargs) -> None:
    """Pull raw klines from Binance public REST API and push to XCom."""
    params = {"symbol": SYMBOL, "interval": INTERVAL, "limit": LIMIT}
    logger.info("Requesting klines: %s %s", BINANCE_KLINES_URL, params)

    resp = requests.get(BINANCE_KLINES_URL, params=params, timeout=30)
    resp.raise_for_status()

    data = resp.json()
    logger.info("Received %d klines from Binance", len(data))
    kwargs["ti"].xcom_push(key="raw_klines", value=json.dumps(data))


def transform(**kwargs) -> None:
    """Normalize raw klines via PySpark and push parquet-ready rows to XCom."""
    import sys
    sys.path.insert(0, str(PROJECT_ROOT))
    from compute.ingest_klines import transform_klines

    raw_json = kwargs["ti"].xcom_pull(key="raw_klines", task_ids="extract")
    raw_data = json.loads(raw_json)

    rows = transform_klines(raw_data)
    logger.info("Transformed %d rows", len(rows))
    kwargs["ti"].xcom_push(key="transformed_rows", value=json.dumps(rows))


def load(**kwargs) -> None:
    """Upsert transformed rows into DuckDB curated.btc_ohlcv."""
    import duckdb

    rows_json = kwargs["ti"].xcom_pull(key="transformed_rows", task_ids="transform")
    rows = json.loads(rows_json)

    if not rows:
        logger.warning("No rows to load — skipping")
        return

    # Ensure schema exists
    con = duckdb.connect(str(WAREHOUSE_DB))
    try:
        schema_ddl = SCHEMA_SQL.read_text()
        for statement in schema_ddl.split(";"):
            stmt = statement.strip()
            if stmt:
                con.execute(stmt)

        # Upsert: delete existing rows by open_time, then insert
        open_times = [r["open_time"] for r in rows]
        placeholders = ",".join(["?"] * len(open_times))
        con.execute(
            f"DELETE FROM curated.btc_ohlcv WHERE open_time IN ({placeholders})",
            open_times,
        )

        for row in rows:
            con.execute(
                """
                INSERT INTO curated.btc_ohlcv (
                    open_time, open, high, low, close, volume,
                    close_time, quote_volume, trade_count,
                    taker_buy_base_volume, taker_buy_quote_volume,
                    ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    row["open_time"],
                    row["open"],
                    row["high"],
                    row["low"],
                    row["close"],
                    row["volume"],
                    row["close_time"],
                    row["quote_volume"],
                    row["trade_count"],
                    row["taker_buy_base_volume"],
                    row["taker_buy_quote_volume"],
                    row["ingested_at"],
                ],
            )

        count = con.execute("SELECT COUNT(*) FROM curated.btc_ohlcv").fetchone()[0]
        logger.info("Loaded %d rows. Table now has %d total rows.", len(rows), count)
    finally:
        con.close()


extract_task = PythonOperator(
    task_id="extract",
    python_callable=extract,
    dag=dag,
)

transform_task = PythonOperator(
    task_id="transform",
    python_callable=transform,
    dag=dag,
)

load_task = PythonOperator(
    task_id="load",
    python_callable=load,
    dag=dag,
)

extract_task >> transform_task >> load_task
