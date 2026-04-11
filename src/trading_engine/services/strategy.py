from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from decimal import Decimal
import math
from statistics import mean, stdev

from .actions import SignalAction
from .portfolio import PortfolioSnapshot
from .pricing import PriceBar


@dataclass(frozen=True)
class Signal:
    """Decision output from a strategy for a single symbol."""
    symbol: str
    action: SignalAction
    quantity: Decimal
    price: Decimal
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

# SIMPLE MOVING AVERAGE CROSSOVER STRATEGY ----------------------------------------------------

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
                        price=closes[-1] if closes else Decimal("0"),
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
                    price=closes[-1],
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


# STATISTICAL ARBITRAGE STRATEGY ----------------------------------------------------

class PairsTradingStrategy:
    """
    Statistical Arbitrage strategy using Z-Score of the ratio between two symbols.
    Expects 'symbol_a' and 'symbol_b' in params.
    """

    name = "stat_arb_pairs"

    def generate_signals(
        self,
        prices: list[PriceBar],
        portfolio: PortfolioSnapshot,
        params: dict,
    ) -> list[Signal]:
        symbol_a = params.get("symbol_a", "PEP").upper()
        symbol_b = params.get("symbol_b", "KO").upper()
        window = int(params.get("window", 20))
        entry_threshold = Decimal(str(params.get("entry_threshold", "2.0")))
        trade_quantity = Decimal(str(params.get("trade_quantity", "10")))

        # 1. Organize data by symbol
        bars_by_symbol: dict[str, list[PriceBar]] = defaultdict(list)
        for bar in prices:
            bars_by_symbol[bar.symbol.upper()].append(bar)

        # 2. Align and calculate the ratio (Price A / Price B)
        # We need both prices for the same day to calculate a valid ratio
        a_closes = {b.day: b.close for b in bars_by_symbol.get(symbol_a, [])}
        b_closes = {b.day: b.close for b in bars_by_symbol.get(symbol_b, [])}
        
        common_days = sorted(set(a_closes.keys()) & set(b_closes.keys()))
        ratios = [a_closes[day] / b_closes[day] for day in common_days]

        created_at = datetime.utcnow()
        if len(ratios) < window:
            return [self._hold_signal(symbol_a, "Insufficient history", created_at)]

        # 3. Calculate Z-Score
        current_ratio = ratios[-1]
        historical_ratios = ratios[-window:]
        
        # Convert Decimals to float for standard math lib
        float_ratios = [float(r) for r in historical_ratios]
        avg = mean(float_ratios)
        sd = stdev(float_ratios) if len(float_ratios) > 1 else 1.0
        z_score = (float(current_ratio) - avg) / sd

        signals = []
        
        # 4. Generate Signals based on Mean Reversion
        # If Z-Score is high, Symbol A is overpriced relative to B (Short A, Long B)
        # If Z-Score is low, Symbol A is underpriced relative to B (Long A, Short B)
        
        if z_score > float(entry_threshold):
            # Short A, Buy B (Simplified: focusing on A for this framework)
            signals.append(self._create_signal(symbol_a, SignalAction.SELL, trade_quantity, f"Z-Score {z_score:.2f} > {entry_threshold}", created_at))
        elif z_score < -float(entry_threshold):
            # Buy A, Short B
            signals.append(self._create_signal(symbol_a, SignalAction.BUY, trade_quantity, f"Z-Score {z_score:.2f} < -{entry_threshold}", created_at))
        else:
            signals.append(self._hold_signal(symbol_a, f"Z-Score {z_score:.2f} within neutral band", created_at))

        return signals

    def _create_signal(self, symbol, action, qty, reason, ts, price: Decimal = Decimal("0")) -> Signal:
        return Signal(
            symbol=symbol, action=action, quantity=qty,
            price=price, reason=reason, confidence=Decimal("0.8"),
            strategy_name=self.name, created_at=ts
        )

    def _hold_signal(self, symbol, reason, ts, price: Decimal = Decimal("0")) -> Signal:
        return Signal(
            symbol=symbol, action=SignalAction.HOLD, quantity=Decimal("0"),
            price=price, reason=reason, confidence=Decimal("0"),
            strategy_name=self.name, created_at=ts
        )


# Auction Liquidity Provider Strategy ----------------------------------------------------
class AuctionLiquidityStrategy:
    """
    Targets the Opening or Closing price by identifying deviations 
    from the 'Expected' price versus the 'Last' price.
    """
    name = "auction_liquidity_provider"

    def generate_signals(
        self,
        prices: list[PriceBar],
        portfolio: PortfolioSnapshot,
        params: dict,
    ) -> list[Signal]:
        # deviation_threshold: How far away from the day's average 
        # should the open/close be for us to take the trade?
        dev_threshold = Decimal(str(params.get("deviation_threshold", "0.02"))) # 2%
        trade_size = Decimal(str(params.get("trade_size", "50")))
        
        created_at = datetime.utcnow()
        signals = []

        # We need the full day's context to know if the Open/Close is "fair"
        bars_by_symbol = defaultdict(list)
        for bar in prices:
            bars_by_symbol[bar.symbol.upper()].append(bar)

        for symbol, symbol_bars in bars_by_symbol.items():
            if not symbol_bars: continue
            
            sorted_bars = sorted(symbol_bars, key=lambda b: b.day)
            latest_bar = sorted_bars[-1]
            
            # Calculate a 'Normal' price (e.g., 5-day moving average of closes)
            # This helps us identify if the current opening/closing price is an outlier.
            historical_closes = [b.close for b in sorted_bars[-5:]]
            fair_value = sum(historical_closes) / len(historical_closes)
            
            # Distance from fair value
            price_gap = (latest_bar.close - fair_value) / fair_value

            # If the price is gaping UP at the open/close (Relative to fair value), 
            # we provide liquidity by SELLING.
            if price_gap > dev_threshold:
                signals.append(Signal(
                    symbol=symbol,
                    action=SignalAction.SELL,
                    quantity=trade_size,
                    price=latest_bar.close,
                    reason=f"Selling price spike: {price_gap:.2%} deviation",
                    confidence=Decimal("0.7"),
                    strategy_name=self.name,
                    created_at=created_at
                ))

            # If the price is gaping DOWN, we BUY.
            elif price_gap < -dev_threshold:
                signals.append(Signal(
                    symbol=symbol,
                    action=SignalAction.BUY,
                    quantity=trade_size,
                    price=latest_bar.close,
                    reason=f"Buying price dip: {price_gap:.2%} deviation",
                    confidence=Decimal("0.7"),
                    strategy_name=self.name,
                    created_at=created_at
                ))

        return signals