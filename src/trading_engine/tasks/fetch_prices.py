from __future__ import annotations
from datetime import date
from celery import shared_task

from src.trading_engine.services.pricing import (
    get_all_enabled_simulator_tickers,
    PricingService,
    SqlPriceBarRepository,
    YahooPriceProvider,
)

@shared_task(name="trading_engine.fetch_prices")
def fetch_prices(tickers: list[str] | None = None, day: str | None = None) -> int:
    """
    Fetch and store daily bars for the given tickers and day.
    day is an ISO date string (YYYY-MM-DD).

    If no tickers arguments is specified, it will fetch all tickers that are in the DB to track
    """
    service = PricingService(provider=YahooPriceProvider(), repo=SqlPriceBarRepository())
    if not tickers:
        tickers = get_all_enabled_simulator_tickers()
    if not day:
        day = date.today().isoformat()
    return service.fetch_and_store_daily_bars(
        symbols=tickers,
        day=date.fromisoformat(day),
    )


@shared_task(name="trading_engine.backfill_prices")
def backfill_prices(
    tickers: list[str] | None = None,
    start_day: str | None = None,
    end_day: str | None = None,
) -> int:
    """
    Backfill daily bars for the given tickers between start_day and end_day (inclusive).
    Dates are ISO strings (YYYY-MM-DD).
    """

    if not tickers:
        tickers = get_all_enabled_simulator_tickers()
    if not start_day or not end_day:
        raise ValueError("start_day and end_day are required for backfill_prices")
    provider = YahooPriceProvider()
    bars = provider.fetch_daily_bars_range(
        symbols=tickers,
        start_day=date.fromisoformat(start_day),
        end_day=date.fromisoformat(end_day),
    )
    repo = SqlPriceBarRepository()
    return repo.upsert_bars(bars)
