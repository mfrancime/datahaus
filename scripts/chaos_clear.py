#!/usr/bin/env python3
"""Chaos recovery: un-pause the Binance klines DAG via Airflow REST API.

Reverses the effect of chaos_freshness.py. The DAG will resume on its
next scheduled interval, and the freshness check should pass once new
data is ingested.
"""

import sys

import requests

AIRFLOW_API = "http://localhost:8080/api/v1"
DAG_ID = "binance_klines_1m"
AUTH = ("admin", "admin")


def main() -> None:
    url = f"{AIRFLOW_API}/dags/{DAG_ID}"

    resp = requests.get(url, auth=AUTH, timeout=10)
    if resp.status_code != 200:
        print(f"ERROR: Could not reach DAG '{DAG_ID}': {resp.status_code} {resp.text}")
        sys.exit(1)

    current_state = resp.json().get("is_paused")
    if current_state is False:
        print(f"DAG '{DAG_ID}' is already active. No action taken.")
        return

    resp = requests.patch(
        url, json={"is_paused": False}, auth=AUTH, timeout=10
    )
    resp.raise_for_status()

    print(f"CHAOS CLEARED: DAG '{DAG_ID}' is now ACTIVE.")
    print("Next scheduled run will ingest fresh data.")
    print("Run 'make trigger-pipeline' to trigger immediately, then 'make run-checks'.")


if __name__ == "__main__":
    main()
