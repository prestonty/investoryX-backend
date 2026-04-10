from __future__ import annotations

from datetime import date
from celery import shared_task

from src.trading_engine.services.backtest import BacktestService


@shared_task(name="trading_engine.run_backtest", bind=True)
def run_backtest_task(
    self,
    simulator_id: int,
    start_date: str,
    end_date: str,
    price_mode: str = "close",
    clear_previous: bool = True,
) -> dict:
    """Run a backtest for a simulator over a historical date range.

    Args:
        simulator_id: The simulator to backtest.
        start_date: ISO date string (YYYY-MM-DD) for the start of the range.
        end_date: ISO date string (YYYY-MM-DD) for the end of the range.
        price_mode: "open" or "close" — which price to use for trade fills.
        clear_previous: If True, delete prior backtest rows before running.

    Returns:
        Serializable dict matching BacktestResult.to_dict().
    """
    service = BacktestService()
    result = service.run(
        simulator_id=simulator_id,
        start_date=date.fromisoformat(start_date),
        end_date=date.fromisoformat(end_date),
        price_mode=price_mode,
        clear_previous=clear_previous,
    )
    return result.to_dict()
