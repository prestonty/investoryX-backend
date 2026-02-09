from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .portfolio import PortfolioSnapshot
from .pricing import PriceBar


@dataclass(frozen=True)
class Signal:
    """Decision output from a strategy for a single symbol."""
    symbol: str
    action: str  # buy | sell | hold
    quantity: float
    reason: str
    confidence: float
    strategy_name: str
    created_at: datetime


class Strategy(Protocol):
    """Strategy contract for generating signals from prices + portfolio."""
    name: str

    def generate_signals(
        self,
        prices: list[PriceBar],
        portfolio: PortfolioSnapshot,
        params: dict,
    ) -> list[Signal]:
        raise NotImplementedError


class StrategyRegistry:
    """In-memory registry for strategy implementations."""
    def __init__(self) -> None:
        self._strategies: dict[str, Strategy] = {}

    def register(self, strategy: Strategy) -> None:
        self._strategies[strategy.name] = strategy

    def get(self, name: str) -> Strategy:
        return self._strategies[name]


class StrategyService:
    """Coordinates strategy lookup and evaluation."""
    def __init__(self, registry: StrategyRegistry) -> None:
        self._registry = registry

    def evaluate(
        self,
        strategy_name: str,
        prices: list[PriceBar],
        portfolio: PortfolioSnapshot,
        params: dict,
    ) -> list[Signal]:
        strategy = self._registry.get(strategy_name)
        return strategy.generate_signals(prices, portfolio, params)
