from __future__ import annotations
from datetime import date
from celery import shared_task

from src.trading_engine.services.pricing import (
    PricingService,
    SqlPriceBarRepository,
    YahooPriceProvider,
)

@shared_task(name="trading_engine.fetch_prices")
def fetch_prices(tickers: list[str], day: str) -> int:
    """
    Fetch and store daily bars for the given tickers and day.
    day is an ISO date string (YYYY-MM-DD).
    """
    service = PricingService(provider=YahooPriceProvider(), repo=SqlPriceBarRepository())
    return service.fetch_and_store_daily_bars(
        symbols=tickers,
        day=date.fromisoformat(day),
    )


@shared_task(name="trading_engine.backfill_prices")
def backfill_prices(tickers: list[str], start_day: str, end_day: str) -> int:
    """
    Backfill daily bars for the given tickers between start_day and end_day (inclusive).
    Dates are ISO strings (YYYY-MM-DD).
    """
    provider = YahooPriceProvider()
    bars = provider.fetch_daily_bars_range(
        symbols=tickers,
        start_day=date.fromisoformat(start_day),
        end_day=date.fromisoformat(end_day),
    )
    repo = SqlPriceBarRepository()
    return repo.upsert_bars(bars)

