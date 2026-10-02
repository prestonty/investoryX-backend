from typing import List

from fastapi import APIRouter

from src.schemas.simulator import StrategyOptionResponse
from src.trading_engine.strategies.catalog import describe_strategies

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


@router.get("", response_model=List[StrategyOptionResponse])
def list_strategies():
    """Available strategies and the settings each one accepts. Public: guests see it too."""
    return describe_strategies()
