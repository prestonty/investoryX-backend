from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(frozen=True)
class PriceBar:
    """Daily OHLCV price record for a single symbol."""
    symbol: str
    day: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    source: str


class PriceProvider(Protocol):
    """Source of price data (API, CSV, etc.)."""
    def fetch_daily_bars(
        self,
        symbols: list[str],
        day: date,
    ) -> list[PriceBar]:
        raise NotImplementedError


class PriceBarRepository(Protocol):
    """Persistence layer for price bars (DB)."""
    def upsert_bars(self, bars: list[PriceBar]) -> int:
        raise NotImplementedError

    def get_latest_bars(self, symbols: list[str], day: date) -> list[PriceBar]:
        raise NotImplementedError


class PricingService:
    """Orchestrates fetching and storing price bars."""
    def __init__(self, provider: PriceProvider, repo: PriceBarRepository) -> None:
        self._provider = provider
        self._repo = repo

    def fetch_and_store_daily_bars(self, symbols: list[str], day: date) -> int:
        bars = self._provider.fetch_dai  ly_bars(symbols, day)
        return self._repo.upsert_bars(bars)

    def get_latest_bars(self, symbols: list[str], day: date) -> list[PriceBar]:
        return self._repo.get_latest_bars(symbols, day)
