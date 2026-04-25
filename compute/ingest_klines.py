"""
PySpark-based transform for Binance klines data.

Takes raw API response (list of lists) and returns a list of typed dicts
ready for DuckDB insertion. Also provides a Spark DataFrame variant for
testing and future batch processing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Column indices in Binance klines response
# https://binance-docs.github.io/apidocs/spot/en/#kline-candlestick-data
_OPEN_TIME = 0
_OPEN = 1
_HIGH = 2
_LOW = 3
_CLOSE = 4
_VOLUME = 5
_CLOSE_TIME = 6
_QUOTE_VOLUME = 7
_TRADE_COUNT = 8
_TAKER_BUY_BASE = 9
_TAKER_BUY_QUOTE = 10


def transform_klines(raw_klines: list[list[Any]]) -> list[dict[str, Any]]:
    """Normalize raw Binance klines into typed dicts.

    Pure function: no side effects, no I/O. Each row gets an ingested_at
    timestamp so Soda can check freshness.
    """
    now = datetime.now(timezone.utc).isoformat()
    rows = []

    for candle in raw_klines:
        rows.append(
            {
                "open_time": candle[_OPEN_TIME],
                "open": float(candle[_OPEN]),
                "high": float(candle[_HIGH]),
                "low": float(candle[_LOW]),
                "close": float(candle[_CLOSE]),
                "volume": float(candle[_VOLUME]),
                "close_time": candle[_CLOSE_TIME],
                "quote_volume": float(candle[_QUOTE_VOLUME]),
                "trade_count": int(candle[_TRADE_COUNT]),
                "taker_buy_base_volume": float(candle[_TAKER_BUY_BASE]),
                "taker_buy_quote_volume": float(candle[_TAKER_BUY_QUOTE]),
                "ingested_at": now,
            }
        )

    return rows


def transform_klines_spark(raw_klines: list[list[Any]]):
    """Return a Spark DataFrame with the canonical OHLCV schema.

    Requires an active SparkSession. Used for testing the transform
    in a Spark context and for future batch processing paths.
    """
    from pyspark.sql import SparkSession
    from pyspark.sql.types import (
        DoubleType,
        IntegerType,
        LongType,
        StringType,
        StructField,
        StructType,
    )

    schema = StructType(
        [
            StructField("open_time", LongType(), False),
            StructField("open", DoubleType(), False),
            StructField("high", DoubleType(), False),
            StructField("low", DoubleType(), False),
            StructField("close", DoubleType(), False),
            StructField("volume", DoubleType(), False),
            StructField("close_time", LongType(), False),
            StructField("quote_volume", DoubleType(), False),
            StructField("trade_count", IntegerType(), False),
            StructField("taker_buy_base_volume", DoubleType(), False),
            StructField("taker_buy_quote_volume", DoubleType(), False),
            StructField("ingested_at", StringType(), False),
        ]
    )

    rows = transform_klines(raw_klines)
    spark = SparkSession.builder.getOrCreate()
    return spark.createDataFrame([tuple(r.values()) for r in rows], schema=schema)
