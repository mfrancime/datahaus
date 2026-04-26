"""Unit tests for exchange adapters (transform only, mocked API data)."""

from compute.adapters.binance import BinanceAdapter
from compute.adapters.bybit import BybitAdapter
from compute.adapters.okx import OKXAdapter

# --- Sample Binance klines response (2 candles) ---
BINANCE_RAW = [
    [
        1704067200000, "42000.50", "42100.00", "41950.25", "42050.75",
        "123.456", 1704067259999, "5189234.56", 1500,
        "61.728", "2594617.28", "0",
    ],
    [
        1704067260000, "42050.75", "42150.00", "42000.00", "42125.50",
        "98.765", 1704067319999, "4156789.01", 1200,
        "49.382", "2078394.50", "0",
    ],
]

# --- Sample Bybit v5 klines (already reversed to chronological) ---
BYBIT_RAW = [
    ["1704067200000", "42000.50", "42100.00", "41950.25", "42050.75", "123.456", "5189234.56"],
    ["1704067260000", "42050.75", "42150.00", "42000.00", "42125.50", "98.765", "4156789.01"],
]

# --- Sample OKX v5 candles (already reversed to chronological) ---
OKX_RAW = [
    ["1704067200000", "42000.50", "42100.00", "41950.25", "42050.75", "123.456", "123.456", "5189234.56", "1"],
    ["1704067260000", "42050.75", "42150.00", "42000.00", "42125.50", "98.765", "98.765", "4156789.01", "0"],
]


# ── Binance adapter ──

class TestBinanceAdapter:
    def test_name(self):
        assert BinanceAdapter().name == "binance"

    def test_transform_count(self):
        rows = BinanceAdapter().transform(BINANCE_RAW)
        assert len(rows) == 2

    def test_transform_exchange_field(self):
        rows = BinanceAdapter().transform(BINANCE_RAW)
        assert all(r["exchange"] == "binance" for r in rows)

    def test_transform_types(self):
        row = BinanceAdapter().transform(BINANCE_RAW)[0]
        assert isinstance(row["open_time"], int)
        assert isinstance(row["open"], float)
        assert isinstance(row["close"], float)
        assert isinstance(row["volume"], float)
        assert isinstance(row["trade_count"], int)
        assert isinstance(row["ingested_at"], str)

    def test_transform_values(self):
        row = BinanceAdapter().transform(BINANCE_RAW)[0]
        assert row["open_time"] == 1704067200000
        assert row["open"] == 42000.50
        assert row["close"] == 42050.75
        assert row["trade_count"] == 1500
        assert row["close_time"] == 1704067259999
        assert row["confirm"] is None

    def test_transform_binance_specific_fields_present(self):
        row = BinanceAdapter().transform(BINANCE_RAW)[0]
        assert row["close_time"] is not None
        assert row["quote_volume"] is not None
        assert row["taker_buy_base_volume"] is not None
        assert row["taker_buy_quote_volume"] is not None

    def test_transform_empty(self):
        assert BinanceAdapter().transform([]) == []


# ── Bybit adapter ──

class TestBybitAdapter:
    def test_name(self):
        assert BybitAdapter().name == "bybit"

    def test_transform_count(self):
        rows = BybitAdapter().transform(BYBIT_RAW)
        assert len(rows) == 2

    def test_transform_exchange_field(self):
        rows = BybitAdapter().transform(BYBIT_RAW)
        assert all(r["exchange"] == "bybit" for r in rows)

    def test_transform_types(self):
        row = BybitAdapter().transform(BYBIT_RAW)[0]
        assert isinstance(row["open_time"], int)
        assert isinstance(row["open"], float)
        assert isinstance(row["close"], float)
        assert isinstance(row["volume"], float)
        assert isinstance(row["ingested_at"], str)

    def test_transform_values(self):
        row = BybitAdapter().transform(BYBIT_RAW)[0]
        assert row["open_time"] == 1704067200000
        assert row["open"] == 42000.50
        assert row["close"] == 42050.75
        assert row["quote_volume"] == 5189234.56

    def test_transform_nullable_fields(self):
        row = BybitAdapter().transform(BYBIT_RAW)[0]
        assert row["close_time"] is None
        assert row["trade_count"] is None
        assert row["taker_buy_base_volume"] is None
        assert row["taker_buy_quote_volume"] is None
        assert row["confirm"] is None

    def test_transform_empty(self):
        assert BybitAdapter().transform([]) == []


# ── OKX adapter ──

class TestOKXAdapter:
    def test_name(self):
        assert OKXAdapter().name == "okx"

    def test_transform_count(self):
        rows = OKXAdapter().transform(OKX_RAW)
        assert len(rows) == 2

    def test_transform_exchange_field(self):
        rows = OKXAdapter().transform(OKX_RAW)
        assert all(r["exchange"] == "okx" for r in rows)

    def test_transform_types(self):
        row = OKXAdapter().transform(OKX_RAW)[0]
        assert isinstance(row["open_time"], int)
        assert isinstance(row["open"], float)
        assert isinstance(row["close"], float)
        assert isinstance(row["confirm"], bool)
        assert isinstance(row["ingested_at"], str)

    def test_transform_values(self):
        row = OKXAdapter().transform(OKX_RAW)[0]
        assert row["open_time"] == 1704067200000
        assert row["open"] == 42000.50
        assert row["close"] == 42050.75
        assert row["confirm"] is True

    def test_transform_confirm_flag(self):
        rows = OKXAdapter().transform(OKX_RAW)
        assert rows[0]["confirm"] is True   # "1" → True
        assert rows[1]["confirm"] is False  # "0" → False

    def test_transform_nullable_fields(self):
        row = OKXAdapter().transform(OKX_RAW)[0]
        assert row["close_time"] is None
        assert row["trade_count"] is None
        assert row["taker_buy_base_volume"] is None
        assert row["taker_buy_quote_volume"] is None

    def test_transform_empty(self):
        assert OKXAdapter().transform([]) == []
