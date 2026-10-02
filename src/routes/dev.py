from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from src.core.config import settings
from src.core.rate_limit import RateLimit
from src.core.security import get_current_active_user
from src.models.users import Users
from src.trading_engine.services.pricing import last_completed_trading_day
from src.trading_engine.tasks.daily_pipeline import MissingPriceDataError, run_pipeline

router = APIRouter(prefix="/dev", tags=["dev"])

# Older days are refused: running the pipeline for a past day would fill live
# trades at that day's historical prices.
MAX_PIPELINE_LOOKBACK_DAYS = 7


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


@router.post(
    "/run-pipeline",
    dependencies=[Depends(RateLimit("dev_pipeline", limit=5, window_seconds=60))],
)
def run_pipeline_now(
    day: date | None = Query(default=None, description="ISO date (YYYY-MM-DD) to run the pipeline for"),
    current_user: Users = Depends(get_current_active_user),
):
    """Run the daily pipeline for every simulator. Dev mode only; affects all users."""
    if not settings.dev_mode:
        raise HTTPException(status_code=403, detail="Only available in dev mode")

    latest_day = last_completed_trading_day()
    if day is not None and not (
        latest_day - timedelta(days=MAX_PIPELINE_LOOKBACK_DAYS) <= day <= latest_day
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                f"day must be between {MAX_PIPELINE_LOOKBACK_DAYS} days before "
                f"{latest_day.isoformat()} and {latest_day.isoformat()}"
            ),
        )

    try:
        return run_pipeline(day=day)
    except MissingPriceDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
