from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal

from celery import shared_task

from src.api.database.database import SessionLocal
from src.trading_engine.services.execution import (
    ExecutionSummary,
    PaperTradeExecutionService,
)


@shared_task(name="trading_engine.execute_paper_trades")
def record_paper_trades(
    simulator_id: int | None = None,
    limit: int = 500,
    slippage_bps: str | Decimal = "0",
    fee_per_trade: str | Decimal = "0",
) -> dict:
    summary = execute_signals(
        simulator_id=simulator_id,
        limit=limit,
        slippage_bps=slippage_bps,
        fee_per_trade=fee_per_trade,
    )
    return asdict(summary)


def execute_signals(
    simulator_id: int | None = None,
    limit: int = 500,
    slippage_bps: str | Decimal = "0",
    fee_per_trade: str | Decimal = "0",
) -> ExecutionSummary:
    # Task orchestration only: normalize boundary inputs and delegate business logic.
    service = PaperTradeExecutionService()
    session = SessionLocal()
    try:
        return service.execute_pending_signals(
            session=session,
            simulator_id=simulator_id,
            limit=limit,
            slippage_bps=Decimal(str(slippage_bps)),
            fee_per_trade=Decimal(str(fee_per_trade)),
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
