from __future__ import annotations

from dataclasses import asdict
from datetime import date

from celery import shared_task

from src.core.config import settings
from src.trading_engine.services.evaluation import EvaluationService
from src.trading_engine.services.pricing import (
    _is_trading_day,
    get_all_enabled_simulator_tickers,
    last_completed_trading_day,
    PricingService,
    SqlPriceBarRepository,
    YahooPriceProvider,
)
from src.trading_engine.tasks.execute_paper_trades import execute_signals
from src.trading_engine.tasks.reconcile_portfolios import reconcile_portfolios


PRICE_RETRY_DELAY_SECONDS = 600


class MissingPriceDataError(RuntimeError):
    """Tracked tickers exist but no price bars could be fetched for the target day."""


def run_pipeline(day: date | None = None, simulator_id: int | None = None) -> dict:
    """Run fetch -> execute -> reconcile -> evaluate in order for one trading day.

    Execution fills the previous trading day's signals at this day's open, then
    evaluation decides on this day's close; those signals fill at the next open.
    Evaluating last means strategies see the portfolio after today's fills.

    Scoped to a single simulator when simulator_id is given (manual runs),
    otherwise covers every simulator (scheduled run).
    """
    target_day = day or last_completed_trading_day()
    if not _is_trading_day(target_day):
        return {"day": target_day.isoformat(), "skipped": "not a trading day"}

    tickers = get_all_enabled_simulator_tickers(simulator_id)
    prices_fetched = 0
    if tickers:
        prices_fetched = PricingService(
            provider=YahooPriceProvider(),
            repo=SqlPriceBarRepository(),
        ).fetch_and_store_daily_bars(symbols=tickers, day=target_day)
        if prices_fetched == 0:
            raise MissingPriceDataError(
                f"No price bars fetched for {len(tickers)} tickers on {target_day.isoformat()}"
            )

    execution = execute_signals(
        simulator_id=simulator_id,
        slippage_bps=settings.sim_slippage_bps,
        fee_per_trade=settings.sim_fee_per_trade,
        day=target_day,
    )
    reconciliation = reconcile_portfolios(simulator_id=simulator_id)
    evaluation = EvaluationService().run(as_of_day=target_day, simulator_id=simulator_id)

    # Key names match the original /dev/run-pipeline response the frontend reads.
    return {
        "day": target_day.isoformat(),
        "prices_fetched": prices_fetched,
        "signals": evaluation.to_dict(),
        "trades_executed": asdict(execution),
        "portfolios_reconciled": reconciliation,
    }


@shared_task(name="trading_engine.run_daily_pipeline", bind=True, max_retries=3)
def run_daily_pipeline(self, day: str | None = None) -> dict:
    try:
        return run_pipeline(day=date.fromisoformat(day) if day else None)
    except MissingPriceDataError as exc:
        # The provider may not have published the day's bars yet; try again later.
        raise self.retry(exc=exc, countdown=PRICE_RETRY_DELAY_SECONDS)
