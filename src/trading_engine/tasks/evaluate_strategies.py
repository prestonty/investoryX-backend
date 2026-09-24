from __future__ import annotations

from datetime import date

from celery import shared_task

from src.trading_engine.services.evaluation import EvaluationService


@shared_task(name="trading_engine.evaluate_strategies")
def evaluate_strategies(
    user_id: int | None = None,
    params: dict | None = None,
    day: str | None = None,
    simulator_id: int | None = None,
) -> dict:
    """Evaluate strategies on `day`'s prices (ISO date; defaults to the last completed trading day)."""
    service = EvaluationService()
    return service.run(
        user_id=user_id,
        params=params,
        as_of_day=date.fromisoformat(day) if day else None,
        simulator_id=simulator_id,
    ).to_dict()
