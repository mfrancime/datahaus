"""OKX exchange adapter for BTC/USDT klines."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import requests

from compute.adapters.base import ExchangeAdapter

logger = logging.getLogger(__name__)

# OKX v5 /market/candles response fields (per candle list):
# [0] ts (ms), [1] o, [2] h, [3] l, [4] c,
# [5] vol (base), [6] volCcy (quote in coin), [7] volCcyQuote (quote in USDT),
# [8] confirm (0=incomplete, 1=complete)
# Response returns newest-first — must reverse for chronological order.
_TS = 0
_OPEN = 1
_HIGH = 2
_LOW = 3
_CLOSE = 4
_VOL = 5
_VOL_CCY = 6
_VOL_CCY_QUOTE = 7
_CONFIRM = 8

OKX_CANDLES_URL = "https://www.okx.com/api/v5/market/candles"


class OKXAdapter(ExchangeAdapter):
    """Adapter for OKX v5 market candles API."""

    @property
    def name(self) -> str:
        return "okx"

    def fetch_raw(self, symbol: str = "BTC-USDT", interval: str = "1m", limit: int = 100) -> list[Any]:
        params = {"instId": symbol, "bar": interval, "limit": str(limit)}
        logger.info("OKX: requesting candles %s", params)
        resp = requests.get(OKX_CANDLES_URL, params=params, timeout=30)
        resp.raise_for_status()
        body = resp.json()
        if body.get("code") != "0":
            raise RuntimeError(f"OKX API error: {body.get('msg')}")
        data = body.get("data", [])
        # OKX returns newest-first; reverse for chronological order
        data.reverse()
        logger.info("OKX: received %d candles", len(data))
        return data

    def transform(self, raw_data: list[Any]) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for candle in raw_data:
            rows.append(
                {
                    "exchange": self.name,
                    "open_time": int(candle[_TS]),
                    "open": float(candle[_OPEN]),
                    "high": float(candle[_HIGH]),
                    "low": float(candle[_LOW]),
                    "close": float(candle[_CLOSE]),
                    "volume": float(candle[_VOL]),
                    "close_time": None,
                    "quote_volume": float(candle[_VOL_CCY_QUOTE]),
                    "trade_count": None,
                    "taker_buy_base_volume": None,
                    "taker_buy_quote_volume": None,
                    "confirm": candle[_CONFIRM] == "1",
                    "ingested_at": now,
                }
            )
        return rows
