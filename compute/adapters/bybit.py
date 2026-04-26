"""Bybit exchange adapter for BTC/USDT klines."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import requests

from compute.adapters.base import ExchangeAdapter

logger = logging.getLogger(__name__)

# Bybit v5 /market/kline response fields (per candle list):
# [0] startTime (ms), [1] openPrice, [2] highPrice, [3] lowPrice,
# [4] closePrice, [5] volume (base), [6] turnover (quote volume)
# Response returns newest-first — must reverse for chronological order.
_START_TIME = 0
_OPEN = 1
_HIGH = 2
_LOW = 3
_CLOSE = 4
_VOLUME = 5
_TURNOVER = 6

BYBIT_KLINES_URL = "https://api.bybit.com/v5/market/kline"


class BybitAdapter(ExchangeAdapter):
    """Adapter for Bybit v5 market klines API."""

    @property
    def name(self) -> str:
        return "bybit"

    def fetch_raw(self, symbol: str = "BTCUSDT", interval: str = "1", limit: int = 100) -> list[Any]:
        params = {"category": "spot", "symbol": symbol, "interval": interval, "limit": limit}
        logger.info("Bybit: requesting klines %s", params)
        resp = requests.get(BYBIT_KLINES_URL, params=params, timeout=30)
        resp.raise_for_status()
        body = resp.json()
        if body.get("retCode") != 0:
            raise RuntimeError(f"Bybit API error: {body.get('retMsg')}")
        data = body.get("result", {}).get("list", [])
        # Bybit returns newest-first; reverse for chronological order
        data.reverse()
        logger.info("Bybit: received %d klines", len(data))
        return data

    def transform(self, raw_data: list[Any]) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for candle in raw_data:
            rows.append(
                {
                    "exchange": self.name,
                    "open_time": int(candle[_START_TIME]),
                    "open": float(candle[_OPEN]),
                    "high": float(candle[_HIGH]),
                    "low": float(candle[_LOW]),
                    "close": float(candle[_CLOSE]),
                    "volume": float(candle[_VOLUME]),
                    "close_time": None,
                    "quote_volume": float(candle[_TURNOVER]),
                    "trade_count": None,
                    "taker_buy_base_volume": None,
                    "taker_buy_quote_volume": None,
                    "confirm": None,
                    "ingested_at": now,
                }
            )
        return rows
