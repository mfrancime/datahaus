"""
Cross-exchange reconciliation DAG.

Queries the last 10 minutes of prices from all exchanges,
detects spread anomalies, and routes alerts via the alert router.
Offset 2 minutes from ingestion DAGs to ensure fresh data is available.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.operators.python import PythonOperator

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WAREHOUSE_DB = PROJECT_ROOT / "warehouse" / "datahaus.duckdb"

default_args = {
    "owner": "datahaus",
    "retries": 1,
    "retry_delay": timedelta(minutes=1),
    "execution_timeout": timedelta(minutes=5),
}

dag = DAG(
    dag_id="reconciliation",
    default_args=default_args,
    description="Cross-exchange spread anomaly detection",
    schedule_interval="2-57/5 * * * *",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["phase-2", "reconciliation"],
)


def reconcile(**kwargs) -> None:
    """Query recent prices from all exchanges and check for spread anomalies."""
    import sys
    sys.path.insert(0, str(PROJECT_ROOT))

    import duckdb
    from compute.reconciliation import detect_spread_anomalies, summarize_anomalies
    from observability.alert_router import route_alert

    con = duckdb.connect(str(WAREHOUSE_DB), read_only=True)
    try:
        # Get rows from the last 10 minutes (600_000 ms)
        rows = con.execute(
            """
            SELECT exchange, open_time, close
            FROM curated.btc_ohlcv
            WHERE open_time >= (
                (EXTRACT(EPOCH FROM NOW()) * 1000)::BIGINT - 600000
            )
            ORDER BY open_time
            """
        ).fetchall()
    finally:
        con.close()

    if not rows:
        logger.info("No recent rows found — skipping reconciliation")
        return

    row_dicts = [{"exchange": r[0], "open_time": r[1], "close": r[2]} for r in rows]
    logger.info("Reconciling %d rows across exchanges", len(row_dicts))

    anomalies = detect_spread_anomalies(row_dicts)
    summary = summarize_anomalies(anomalies)

    if anomalies:
        logger.warning("Spread anomalies detected:\n%s", summary)
        route_alert(
            check_name="spread_anomaly",
            table="curated.btc_ohlcv",
            exchange="cross-exchange",
            outcome="FAIL",
            details=summary,
        )
    else:
        logger.info("No spread anomalies — all exchanges within threshold")
        route_alert(
            check_name="spread_anomaly",
            table="curated.btc_ohlcv",
            exchange="cross-exchange",
            outcome="PASS",
            details="No spread anomalies detected.",
        )


reconcile_task = PythonOperator(
    task_id="reconcile",
    python_callable=reconcile,
    dag=dag,
)
