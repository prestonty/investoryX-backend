from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from celery import shared_task

from src.core.database import SessionLocal
from src.trading_engine.services.manual_orders import ManualOrderService


@shared_task(name="trading_engine.fill_queued_orders")
def run_fill_queued_orders() -> dict:
    return fill_queued_orders()


def fill_queued_orders(
    simulator_id: int | None = None,
    now: datetime | None = None,
) -> dict:
    """Fill manual orders queued while the market was closed, at their day's open."""
    session = SessionLocal()
    try:
        summary = ManualOrderService().fill_due_orders(
            session=session, now=now, simulator_id=simulator_id
        )
        return asdict(summary)
    finally:
        session.close()
