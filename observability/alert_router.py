"""Alert router — file-based logging with optional Slack webhook.

Always writes alerts to observability/alerts/alert_log.jsonl.
If SLACK_WEBHOOK_URL is set, also POSTs a formatted message to Slack.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALERT_LOG = PROJECT_ROOT / "observability" / "alerts" / "alert_log.jsonl"


def route_alert(
    check_name: str,
    table: str,
    exchange: str,
    outcome: str,
    details: str,
) -> dict:
    """Route an alert to file (always) and Slack (if configured).

    Args:
        check_name: Name of the check or alert type (e.g. 'spread_anomaly').
        table: Table being checked (e.g. 'curated.btc_ohlcv').
        exchange: Exchange involved ('binance', 'bybit', 'okx', 'cross-exchange').
        outcome: 'PASS', 'FAIL', or 'WARN'.
        details: Human-readable details string.

    Returns:
        The alert record dict that was written.
    """
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "check_name": check_name,
        "table": table,
        "exchange": exchange,
        "outcome": outcome,
        "details": details,
    }

    # Always write to JSONL file
    ALERT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(ALERT_LOG, "a") as f:
        f.write(json.dumps(record) + "\n")
    logger.info("Alert logged: [%s] %s / %s — %s", outcome, check_name, exchange, details[:100])

    # Optional Slack webhook
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if webhook_url:
        icon = {"PASS": ":white_check_mark:", "FAIL": ":rotating_light:", "WARN": ":warning:"}.get(outcome, ":question:")
        slack_msg = {
            "text": f"{icon} *[datahaus] {check_name}*\n"
                    f"Exchange: `{exchange}` | Table: `{table}` | Outcome: *{outcome}*\n"
                    f"```{details}```",
        }
        try:
            resp = requests.post(webhook_url, json=slack_msg, timeout=10)
            resp.raise_for_status()
            logger.info("Slack alert sent successfully")
        except Exception:
            logger.exception("Failed to send Slack alert (non-fatal)")

    return record
