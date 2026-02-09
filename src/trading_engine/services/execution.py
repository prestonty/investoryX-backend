from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .portfolio import PortfolioSnapshot
from .strategy import Signal


@dataclass(frozen=True)
class ExecutionRules:
    """Risk and cost constraints applied during paper execution."""
    max_position_pct: float
    max_order_value: float
    fee_per_trade: float
    slippage_bps: float


@dataclass(frozen=True)
class Trade:
    """Executed paper trade derived from a signal."""
    symbol: str
    side: str  # buy | sell
    quantity: float
    price: float
    fee: float
    executed_at: datetime
    strategy_name: str


class ExecutionService:
    """Turns signals into paper trades using rules and prices."""
    def execute_signals(
        self,
        signals: list[Signal],
        portfolio: PortfolioSnapshot,
        rules: ExecutionRules,
        prices: dict[str, float],
    ) -> list[Trade]:
        raise NotImplementedError
