#!/usr/bin/env python3
"""Chaos injection: pause an exchange klines DAG via Airflow REST API.

This simulates a pipeline stall. After enough time passes, the Soda
freshness check for that exchange will fail — just like a real
production incident where an upstream pipeline stops delivering data.

Usage:
    python chaos_freshness.py                  # pause binance (default)
    python chaos_freshness.py --exchange bybit
    python chaos_freshness.py --exchange all
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


def pause_dag(dag_id: str) -> None:
    url = f"{AIRFLOW_API}/dags/{dag_id}"

    resp = requests.get(url, auth=AUTH, timeout=10)
    if resp.status_code != 200:
        print(f"ERROR: Could not reach DAG '{dag_id}': {resp.status_code} {resp.text}")
        sys.exit(1)

    current_state = resp.json().get("is_paused")
    if current_state is True:
        print(f"DAG '{dag_id}' is already paused. No action taken.")
        return

    resp = requests.patch(
        url, json={"is_paused": True}, auth=AUTH, timeout=10
    )
    resp.raise_for_status()

    print(f"CHAOS INJECTED: DAG '{dag_id}' is now PAUSED.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Chaos: pause exchange DAG(s)")
    parser.add_argument(
        "--exchange",
        choices=list(DAG_IDS.keys()) + ["all"],
        default="binance",
        help="Exchange DAG to pause (default: binance)",
    )
    args = parser.parse_args()

    targets = list(DAG_IDS.items()) if args.exchange == "all" else [(args.exchange, DAG_IDS[args.exchange])]

    for name, dag_id in targets:
        pause_dag(dag_id)

    print("\nThe freshness check will start failing after the threshold expires.")
    print("Run 'make chaos-clear' to un-pause and recover.")


if __name__ == "__main__":
    main()
