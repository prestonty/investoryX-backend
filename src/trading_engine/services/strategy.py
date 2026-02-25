from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from decimal import Decimal

from .actions import SignalAction
from .portfolio import PortfolioSnapshot
from .pricing import PriceBar


@dataclass(frozen=True)
class Signal:
    """Decision output from a strategy for a single symbol."""
    symbol: str
    action: SignalAction
    quantity: Decimal
    reason: str
    confidence: Decimal
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


class SimpleMovingAverageStrategy:
    """Basic SMA crossover strategy for paper trading."""

    name = "sma_crossover"

    def generate_signals(
        self,
        prices: list[PriceBar],
        portfolio: PortfolioSnapshot,
        params: dict,
    ) -> list[Signal]:
        short_window = int(params.get("short_window", 5))
        long_window = int(params.get("long_window", 20))
        trade_quantity = Decimal(str(params.get("trade_quantity", "1")))

        if short_window <= 0 or long_window <= 0:
            raise ValueError("short_window and long_window must be positive")
        if short_window >= long_window:
            raise ValueError("short_window must be smaller than long_window")
        if trade_quantity <= 0:
            raise ValueError("trade_quantity must be positive")

        bars_by_symbol: dict[str, list[PriceBar]] = defaultdict(list)
        for bar in prices:
            bars_by_symbol[bar.symbol.upper()].append(bar)

        created_at = datetime.utcnow()
        signals: list[Signal] = []

        for symbol, symbol_bars in bars_by_symbol.items():
            sorted_bars = sorted(symbol_bars, key=lambda bar: bar.day)
            closes = [bar.close for bar in sorted_bars]

            if len(closes) < long_window:
                signals.append(
                    Signal(
                        symbol=symbol,
                        action=SignalAction.HOLD,
                        quantity=Decimal("0"),
                        reason=(
                            f"Not enough history for SMA crossover "
                            f"({len(closes)}/{long_window} bars)"
                        ),
                        confidence=Decimal("0"),
                        strategy_name=self.name,
                        created_at=created_at,
                    )
                )
                continue

            prev_short = _sma(closes[:-1], short_window)
            prev_long = _sma(closes[:-1], long_window)
            curr_short = _sma(closes, short_window)
            curr_long = _sma(closes, long_window)

            action = SignalAction.HOLD
            quantity = Decimal("0")
            reason = "No crossover signal"

            position = portfolio.positions.get(symbol)
            current_quantity = position.quantity if position else Decimal("0")

            crossed_up = prev_short <= prev_long and curr_short > curr_long
            crossed_down = prev_short >= prev_long and curr_short < curr_long

            if crossed_up:
                action = SignalAction.BUY
                quantity = trade_quantity
                reason = "Short SMA crossed above long SMA"
            elif crossed_down and current_quantity > 0:
                action = SignalAction.SELL
                quantity = min(trade_quantity, current_quantity)
                reason = "Short SMA crossed below long SMA"
            elif crossed_down and current_quantity <= 0:
                reason = "Bearish crossover but no position to sell"

            confidence = _confidence_from_spread(curr_short, curr_long)
            signals.append(
                Signal(
                    symbol=symbol,
                    action=action,
                    quantity=quantity,
                    reason=reason,
                    confidence=confidence,
                    strategy_name=self.name,
                    created_at=created_at,
                )
            )

        return sorted(signals, key=lambda signal: signal.symbol)


def _sma(values: list[Decimal], window: int) -> Decimal:
    if len(values) < window:
        raise ValueError("Insufficient values for SMA calculation")
    segment = values[-window:]
    return sum(segment) / window


def _confidence_from_spread(short_sma: Decimal, long_sma: Decimal) -> Decimal:
    if long_sma == 0:
        return Decimal("0")
    spread_ratio = abs(short_sma - long_sma) / abs(long_sma)
    return min(Decimal("1"), spread_ratio)
