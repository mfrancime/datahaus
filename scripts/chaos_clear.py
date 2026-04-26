#!/usr/bin/env python3
"""Chaos recovery: un-pause exchange klines DAG(s) via Airflow REST API.

Reverses the effect of chaos_freshness.py. The DAG will resume on its
next scheduled interval, and the freshness check should pass once new
data is ingested.

Usage:
    python chaos_clear.py                  # un-pause binance (default)
    python chaos_clear.py --exchange bybit
    python chaos_clear.py --exchange all
"""

import argparse
import sys

import requests

AIRFLOW_API = "http://localhost:8080/api/v1"
AUTH = ("admin", "admin")

DAG_IDS = {
    "binance": "binance_klines_1m",
    "bybit": "bybit_klines_1m",
    "okx": "okx_klines_1m",
}


def unpause_dag(dag_id: str) -> None:
    url = f"{AIRFLOW_API}/dags/{dag_id}"

    resp = requests.get(url, auth=AUTH, timeout=10)
    if resp.status_code != 200:
        print(f"ERROR: Could not reach DAG '{dag_id}': {resp.status_code} {resp.text}")
        sys.exit(1)

    current_state = resp.json().get("is_paused")
    if current_state is False:
        print(f"DAG '{dag_id}' is already active. No action taken.")
        return

    resp = requests.patch(
        url, json={"is_paused": False}, auth=AUTH, timeout=10
    )
    resp.raise_for_status()

    print(f"CHAOS CLEARED: DAG '{dag_id}' is now ACTIVE.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Chaos recovery: un-pause exchange DAG(s)")
    parser.add_argument(
        "--exchange",
        choices=list(DAG_IDS.keys()) + ["all"],
        default="binance",
        help="Exchange DAG to un-pause (default: binance)",
    )
    args = parser.parse_args()

    targets = list(DAG_IDS.items()) if args.exchange == "all" else [(args.exchange, DAG_IDS[args.exchange])]

    for name, dag_id in targets:
        unpause_dag(dag_id)

    print("\nNext scheduled run will ingest fresh data.")
    print("Run 'make trigger-all' to trigger immediately, then 'make run-checks-all'.")


if __name__ == "__main__":
    main()
