from __future__ import annotations
import logging
from datetime import date, timedelta
from celery import shared_task

from src.trading_engine.services.pricing import (
    get_all_enabled_simulator_tickers,
    has_price_history,
    last_completed_trading_day,
    PricingService,
    SqlPriceBarRepository,
    YahooPriceProvider,
)

logger = logging.getLogger("investoryx.trading_engine.fetch_prices")

# Calendar days of history a newly tracked ticker gets. Covers the longest
# strategy lookback: SMA 50/200 loads 201 bars + 201 buffer days = 402 days.
TICKER_HISTORY_DAYS = 420

@shared_task(name="trading_engine.fetch_prices")
def fetch_prices(tickers: list[str] | None = None, day: str | None = None) -> int:
    """
    Fetch and store daily bars for the given tickers and day.
    day is an ISO date string (YYYY-MM-DD).

    If no tickers arguments is specified, it will fetch all tickers that are in the DB to track.
    If no day is specified, it uses the last trading day whose session has closed.
    """
    service = PricingService(provider=YahooPriceProvider(), repo=SqlPriceBarRepository())
    if not tickers:
        tickers = get_all_enabled_simulator_tickers()
    target_day = date.fromisoformat(day) if day else last_completed_trading_day()
    return service.fetch_and_store_daily_bars(
        symbols=tickers,
        day=target_day,
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


@shared_task(name="trading_engine.backfill_ticker_history")
def backfill_ticker_history(ticker: str) -> int:
    """Load a newly tracked ticker's price history so strategies can use it right away.

    Without this the daily pipeline adds one bar per day, leaving the ticker on
    "not enough history" holds for weeks. Skips tickers already covered (e.g.
    tracked by another simulator). Returns the number of bars stored.
    """
    symbol = ticker.strip().upper()
    end_day = last_completed_trading_day()
    start_day = end_day - timedelta(days=TICKER_HISTORY_DAYS)
    if has_price_history(symbol, start_day, end_day):
        return 0

    bars = YahooPriceProvider().fetch_daily_bars_range([symbol], start_day, end_day)
    if not bars:
        logger.warning("No price history found for %s from %s to %s", symbol, start_day, end_day)
        return 0
    return SqlPriceBarRepository().upsert_bars(bars)
