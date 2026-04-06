from fastapi import APIRouter, Depends, HTTPException, Query

from src.core.config import settings
from src.core.security import get_current_active_user
from src.models.users import Users
from src.trading_engine.tasks.fetch_prices import fetch_prices
from src.trading_engine.tasks.evaluate_strategies import evaluate_strategies
from src.trading_engine.tasks.execute_paper_trades import record_paper_trades
from src.trading_engine.tasks.reconcile_portfolios import run_reconciliation

router = APIRouter(prefix="/dev", tags=["dev"])


@router.get("/flags")
def get_flags():
    return {"dev_mode": settings.dev_mode}


@router.post("/run-pipeline")
def run_pipeline(
    _current_user: Users = Depends(get_current_active_user),
    day: str | None = Query(default=None, description="ISO date (YYYY-MM-DD) to fetch prices for"),
):
    if not settings.dev_mode:
        raise HTTPException(status_code=403, detail="Only available in dev mode")

    prices_fetched = fetch_prices.apply(kwargs={"day": day}).get()
    signals = evaluate_strategies.apply().get()
    trades = record_paper_trades.apply().get()
    reconciled = run_reconciliation.apply().get()

    return {
        "prices_fetched": prices_fetched,
        "signals": signals,
        "trades_executed": trades,
        "portfolios_reconciled": reconciled,
    }
