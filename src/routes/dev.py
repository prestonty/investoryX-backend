from datetime import date

from fastapi import APIRouter, HTTPException, Query

from src.core.config import settings
from src.trading_engine.tasks.daily_pipeline import MissingPriceDataError, run_pipeline

router = APIRouter(prefix="/dev", tags=["dev"])


@router.get("/flags")
def get_flags():
    return {"dev_mode": settings.dev_mode}


@router.get("/strategies")
def get_strategies():
    return [
        {"value": "sma_crossover", "label": "SMA Crossover"},
        {"value": "stat_arb_pairs", "label": "Pairs Trading (Stat Arb)"},
        {"value": "auction_liquidity_provider", "label": "Auction Liquidity Provider"},
    ]


@router.get("/run-pipeline")
def run_pipeline_now(
    day: date | None = Query(default=None, description="ISO date (YYYY-MM-DD) to run the pipeline for"),
):
    if not settings.dev_mode:
        raise HTTPException(status_code=403, detail="Only available in dev mode")

    try:
        return run_pipeline(day=day)
    except MissingPriceDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
