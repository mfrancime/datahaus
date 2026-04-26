"""Cross-exchange reconciliation logic.

Pure functions for detecting spread anomalies across exchanges.
No I/O — receives rows, returns anomaly dicts.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def detect_spread_anomalies(
    rows: list[dict[str, Any]],
    threshold: float = 0.01,
) -> list[dict[str, Any]]:
    """Detect close-price spreads exceeding threshold across exchanges.

    Groups rows by open_time, compares close prices for every pair of
    exchanges present. Flags any pair where the relative spread exceeds
    the threshold (default 1%).

    Args:
        rows: List of dicts with at least {exchange, open_time, close}.
        threshold: Maximum acceptable relative spread (0.01 = 1%).

    Returns:
        List of anomaly dicts, each containing:
            open_time, exchange_a, exchange_b, close_a, close_b,
            spread_pct, threshold
    """
    by_time: dict[int, dict[str, float]] = defaultdict(dict)
    for row in rows:
        by_time[row["open_time"]][row["exchange"]] = row["close"]

    anomalies = []
    for open_time, prices in sorted(by_time.items()):
        exchanges = sorted(prices.keys())
        for i in range(len(exchanges)):
            for j in range(i + 1, len(exchanges)):
                ex_a, ex_b = exchanges[i], exchanges[j]
                close_a, close_b = prices[ex_a], prices[ex_b]
                midpoint = (close_a + close_b) / 2
                if midpoint == 0:
                    continue
                spread = abs(close_a - close_b) / midpoint
                if spread > threshold:
                    anomalies.append(
                        {
                            "open_time": open_time,
                            "exchange_a": ex_a,
                            "exchange_b": ex_b,
                            "close_a": close_a,
                            "close_b": close_b,
                            "spread_pct": round(spread * 100, 4),
                            "threshold": threshold,
                        }
                    )
    return anomalies


def summarize_anomalies(anomalies: list[dict[str, Any]]) -> str:
    """Format anomalies into human-readable alert text."""
    if not anomalies:
        return "No spread anomalies detected."

    lines = [f"SPREAD ALERT: {len(anomalies)} anomalies detected\n"]
    for a in anomalies:
        lines.append(
            f"  [{a['open_time']}] {a['exchange_a']}={a['close_a']:.2f} vs "
            f"{a['exchange_b']}={a['close_b']:.2f} "
            f"(spread: {a['spread_pct']:.4f}%, threshold: {a['threshold']*100:.2f}%)"
        )
    return "\n".join(lines)
