from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .portfolio import PortfolioSnapshot
from .strategy import Signal, SignalAction


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
    side: SignalAction
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

@dataclass(frozen=True)
class ExecutionSummary:
    processed: int
    executed: int
    skipped: int
    failed: int
    trades_created: int

@dataclass(frozen=True)
class TradeIntent:
    signal_id: int
    simulator_id: int
    symbol: str
    side: SignalAction
    quantity: Decimal
    reference_price: Decimal
    strategy_name: str | None = None
