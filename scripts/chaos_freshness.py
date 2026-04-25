#!/usr/bin/env python3
"""Chaos injection: pause the Binance klines DAG via Airflow REST API.

This simulates a pipeline stall. After enough time passes, the Soda
freshness check on curated.btc_ohlcv will fail — just like a real
production incident where an upstream pipeline stops delivering data.
"""

import sys

import requests

AIRFLOW_API = "http://localhost:8080/api/v1"
DAG_ID = "binance_klines_1m"
AUTH = ("admin", "admin")


def main() -> None:
    url = f"{AIRFLOW_API}/dags/{DAG_ID}"

    # Verify the DAG exists first
    resp = requests.get(url, auth=AUTH, timeout=10)
    if resp.status_code != 200:
        print(f"ERROR: Could not reach DAG '{DAG_ID}': {resp.status_code} {resp.text}")
        sys.exit(1)

    current_state = resp.json().get("is_paused")
    if current_state is True:
        print(f"DAG '{DAG_ID}' is already paused. No action taken.")
        return

    # Pause the DAG
    resp = requests.patch(
        url, json={"is_paused": True}, auth=AUTH, timeout=10
    )
    resp.raise_for_status()

    print(f"CHAOS INJECTED: DAG '{DAG_ID}' is now PAUSED.")
    print("The freshness check will start failing after the threshold expires.")
    print("Run 'make chaos-clear' to un-pause and recover.")


if __name__ == "__main__":
    main()
