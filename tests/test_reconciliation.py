"""Unit tests for cross-exchange reconciliation logic."""

from compute.reconciliation import detect_spread_anomalies, summarize_anomalies


def _make_row(exchange: str, open_time: int, close: float) -> dict:
    return {"exchange": exchange, "open_time": open_time, "close": close}


class TestDetectSpreadAnomalies:
    def test_no_rows(self):
        assert detect_spread_anomalies([]) == []

    def test_single_exchange_no_anomaly(self):
        rows = [
            _make_row("binance", 1000, 42000.0),
            _make_row("binance", 2000, 42100.0),
        ]
        assert detect_spread_anomalies(rows) == []

    def test_two_exchanges_within_threshold(self):
        rows = [
            _make_row("binance", 1000, 42000.0),
            _make_row("bybit", 1000, 42000.0 * 1.005),  # 0.5% spread — below 1%
        ]
        assert detect_spread_anomalies(rows, threshold=0.01) == []

    def test_two_exchanges_above_threshold(self):
        rows = [
            _make_row("binance", 1000, 42000.0),
            _make_row("bybit", 1000, 42000.0 * 1.02),  # 2% spread — above 1%
        ]
        anomalies = detect_spread_anomalies(rows, threshold=0.01)
        assert len(anomalies) == 1
        a = anomalies[0]
        assert a["open_time"] == 1000
        assert a["exchange_a"] == "binance"
        assert a["exchange_b"] == "bybit"
        assert a["spread_pct"] > 1.0

    def test_three_exchanges_one_divergent(self):
        rows = [
            _make_row("binance", 1000, 42000.0),
            _make_row("bybit", 1000, 42050.0),    # within 1% of binance
            _make_row("okx", 1000, 43000.0),       # ~2.4% off — anomaly
        ]
        anomalies = detect_spread_anomalies(rows, threshold=0.01)
        # okx vs binance and okx vs bybit should both trigger
        assert len(anomalies) == 2
        exchanges_involved = {(a["exchange_a"], a["exchange_b"]) for a in anomalies}
        assert ("binance", "okx") in exchanges_involved
        assert ("bybit", "okx") in exchanges_involved

    def test_multiple_timestamps(self):
        rows = [
            _make_row("binance", 1000, 42000.0),
            _make_row("bybit", 1000, 42000.0 * 1.02),
            _make_row("binance", 2000, 42100.0),
            _make_row("bybit", 2000, 42100.0),  # no spread at t=2000
        ]
        anomalies = detect_spread_anomalies(rows, threshold=0.01)
        assert len(anomalies) == 1
        assert anomalies[0]["open_time"] == 1000

    def test_exact_threshold_not_flagged(self):
        # Spread of exactly 1% should NOT be flagged (> not >=)
        base = 42000.0
        spread_close = base * 1.01  # exactly 1%
        rows = [
            _make_row("binance", 1000, base),
            _make_row("bybit", 1000, spread_close),
        ]
        # The midpoint-based calculation makes this slightly under 1%
        anomalies = detect_spread_anomalies(rows, threshold=0.01)
        assert len(anomalies) == 0

    def test_custom_threshold(self):
        rows = [
            _make_row("binance", 1000, 42000.0),
            _make_row("bybit", 1000, 42000.0 * 1.005),  # 0.5% spread
        ]
        # 0.5% spread exceeds 0.1% threshold
        anomalies = detect_spread_anomalies(rows, threshold=0.001)
        assert len(anomalies) == 1


class TestSummarizeAnomalies:
    def test_no_anomalies(self):
        result = summarize_anomalies([])
        assert "No spread anomalies" in result

    def test_with_anomalies(self):
        anomalies = [
            {
                "open_time": 1000,
                "exchange_a": "binance",
                "exchange_b": "bybit",
                "close_a": 42000.0,
                "close_b": 42840.0,
                "spread_pct": 1.98,
                "threshold": 0.01,
            }
        ]
        result = summarize_anomalies(anomalies)
        assert "SPREAD ALERT" in result
        assert "1 anomalies" in result
        assert "binance" in result
        assert "bybit" in result
