from __future__ import annotations
from datetime import date
from celery import Celery, shared_task

from src.trading_engine.servies.pricing import PricingService, YahooPriceProvider, PriceBarRepository

@shared_task(name="trading_engine.fetch_prices")
def fetch_prices(tickers: list[str], day: str):
    """
    Fetch and store daily bars for the given tickers and day.
    day is an ISO date string (YYYY-MM-DD).
    """
    service = PricingService(provider=YahooPriceProvider(), repo=SqlPriceBarRepository())
    return service.fetch_and_store_daily_bars(tickers=tickers, day=date.fromisoformat(day))
