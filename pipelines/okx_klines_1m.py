"""
OKX BTC/USDT 1-minute klines ingestion pipeline.

Pulls the last 100 one-minute candles from OKX v5 public API,
normalizes them via the OKX adapter, and upserts into DuckDB.
Scheduled every 5 minutes — SequentialExecutor prevents concurrent writes.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.operators.python import PythonOperator

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WAREHOUSE_DB = PROJECT_ROOT / "warehouse" / "datahaus.duckdb"
SCHEMA_SQL = PROJECT_ROOT / "warehouse" / "schema.sql"

default_args = {
    "owner": "datahaus",
    "retries": 3,
    "retry_delay": timedelta(minutes=1),
    "retry_exponential_backoff": True,
    "execution_timeout": timedelta(minutes=5),
}

dag = DAG(
    dag_id="okx_klines_1m",
    default_args=default_args,
    description="Ingest BTC/USDT 1m klines from OKX into DuckDB",
    schedule_interval="*/5 * * * *",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["phase-2", "crypto", "okx"],
)


def extract(**kwargs) -> None:
    """Pull raw candles from OKX v5 public REST API and push to XCom."""
    import sys
    sys.path.insert(0, str(PROJECT_ROOT))
    from compute.adapters.okx import OKXAdapter

    adapter = OKXAdapter()
    data = adapter.fetch_raw()
    kwargs["ti"].xcom_push(key="raw_klines", value=json.dumps(data))


def transform(**kwargs) -> None:
    """Normalize raw candles via adapter and push rows to XCom."""
    import sys
    sys.path.insert(0, str(PROJECT_ROOT))
    from compute.adapters.okx import OKXAdapter

    raw_json = kwargs["ti"].xcom_pull(key="raw_klines", task_ids="extract")
    raw_data = json.loads(raw_json)

    adapter = OKXAdapter()
    rows = adapter.transform(raw_data)
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

    con = duckdb.connect(str(WAREHOUSE_DB))
    try:
        schema_ddl = SCHEMA_SQL.read_text()
        for statement in schema_ddl.split(";"):
            stmt = statement.strip()
            if stmt:
                con.execute(stmt)

        open_times = [r["open_time"] for r in rows]
        placeholders = ",".join(["?"] * len(open_times))
        con.execute(
            f"DELETE FROM curated.btc_ohlcv WHERE exchange = 'okx' AND open_time IN ({placeholders})",
            open_times,
        )

        for row in rows:
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
                    row["exchange"],
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
                    row["confirm"],
                    row["ingested_at"],
                ],
            )

        count = con.execute(
            "SELECT COUNT(*) FROM curated.btc_ohlcv WHERE exchange = 'okx'"
        ).fetchone()[0]
        logger.info("Loaded %d rows. OKX total: %d rows.", len(rows), count)
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
