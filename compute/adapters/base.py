"""Base adapter ABC for exchange klines ingestion."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ExchangeAdapter(ABC):
    """Abstract base for exchange-specific klines adapters.

    Each adapter knows how to fetch raw data from its exchange API
    and transform the response into the unified curated schema.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Exchange identifier used in the `exchange` column (e.g. 'binance')."""

    @abstractmethod
    def fetch_raw(self, symbol: str, interval: str, limit: int) -> list[Any]:
        """Fetch raw klines from the exchange API. Returns raw API response."""

    @abstractmethod
    def transform(self, raw_data: list[Any]) -> list[dict[str, Any]]:
        """Transform raw API response into unified row dicts.

        Each dict must contain at minimum:
            exchange, open_time, open, high, low, close, volume, ingested_at

        Exchange-specific fields (close_time, quote_volume, trade_count,
        taker_buy_base_volume, taker_buy_quote_volume, confirm) should be
        set to None if not available from the exchange.
        """
