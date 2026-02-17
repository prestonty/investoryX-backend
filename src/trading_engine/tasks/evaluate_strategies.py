from __future__ import annotations

from celery import shared_task

from src.trading_engine.services.evaluation import EvaluationService


@shared_task(name="trading_engine.evaluate_strategies")
def evaluate_strategies(
    user_id: int | None = None,
    params: dict | None = None,
) -> dict:
    service = EvaluationService()
    return service.run(user_id=user_id, params=params).to_dict()
