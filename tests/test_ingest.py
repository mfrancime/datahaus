"""Tests for the klines transform logic."""

from compute.ingest_klines import transform_klines

# Sample Binance klines response (2 candles)
SAMPLE_KLINES = [
    [
        1704067200000,      # open_time
        "42000.50",         # open
        "42100.00",         # high
        "41950.25",         # low
        "42050.75",         # close
        "123.456",          # volume
        1704067259999,      # close_time
        "5189234.56",       # quote_volume
        1500,               # trade_count
        "61.728",           # taker_buy_base_volume
        "2594617.28",       # taker_buy_quote_volume
        "0",                # (ignored field)
    ],
    [
        1704067260000,
        "42050.75",
        "42150.00",
        "42000.00",
        "42125.50",
        "98.765",
        1704067319999,
        "4156789.01",
        1200,
        "49.382",
        "2078394.50",
        "0",
    ],
]


def test_transform_returns_correct_count():
    rows = transform_klines(SAMPLE_KLINES)
    assert len(rows) == 2


def test_transform_types():
    rows = transform_klines(SAMPLE_KLINES)
    row = rows[0]
    assert isinstance(row["open_time"], int)
    assert isinstance(row["open"], float)
    assert isinstance(row["high"], float)
    assert isinstance(row["low"], float)
    assert isinstance(row["close"], float)
    assert isinstance(row["volume"], float)
    assert isinstance(row["trade_count"], int)
    assert isinstance(row["ingested_at"], str)


def test_transform_values():
    rows = transform_klines(SAMPLE_KLINES)
    row = rows[0]
    assert row["open_time"] == 1704067200000
    assert row["open"] == 42000.50
    assert row["high"] == 42100.00
    assert row["close"] == 42050.75
    assert row["trade_count"] == 1500


def test_transform_empty_input():
    rows = transform_klines([])
    assert rows == []


def test_transform_no_duplicates():
    rows = transform_klines(SAMPLE_KLINES)
    open_times = [r["open_time"] for r in rows]
    assert len(open_times) == len(set(open_times))
