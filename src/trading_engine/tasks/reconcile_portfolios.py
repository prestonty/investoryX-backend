from __future__ import annotations

from celery import shared_task

from src.api.database.database import SessionLocal
from src.trading_engine.services.portfolio import PortfolioService


@shared_task(name="trading_engine.reconcile_portfolios")
def run_reconciliation(
    simulator_id: int | None = None,
    limit: int = 500,
) -> dict:
    return reconcile_portfolios(simulator_id=simulator_id, limit=limit)


def reconcile_portfolios(
    simulator_id: int | None = None,
    limit: int = 500,
) -> dict:
    service = PortfolioService()
    session = SessionLocal()
    try:
        if simulator_id is not None:
            result = service.reconcile_simulator(
                session=session,
                simulator_id=simulator_id,
            )
            session.commit()
            return {
                "simulator_id": simulator_id,
                "reconciled": 1,
                "results": [result.to_dict()],
            }

        results = service.reconcile_all(session=session, limit=limit)
        session.commit()
        return {
            "simulator_id": None,
            "reconciled": len(results),
            "results": [result.to_dict() for result in results],
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
