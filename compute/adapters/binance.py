"""Binance exchange adapter for BTC/USDT klines."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import requests

from compute.adapters.base import ExchangeAdapter

logger = logging.getLogger(__name__)

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

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"


class BinanceAdapter(ExchangeAdapter):
    """Adapter for Binance spot klines API."""

    @property
    def name(self) -> str:
        return "binance"

    def fetch_raw(self, symbol: str = "BTCUSDT", interval: str = "1m", limit: int = 100) -> list[Any]:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        logger.info("Binance: requesting klines %s", params)
        resp = requests.get(BINANCE_KLINES_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        logger.info("Binance: received %d klines", len(data))
        return data

    def transform(self, raw_data: list[Any]) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for candle in raw_data:
            rows.append(
                {
                    "exchange": self.name,
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
                    "confirm": None,
                    "ingested_at": now,
                }
            )
        return rows
