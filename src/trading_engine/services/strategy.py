from __future__ import annotations

from collections import defaultdict
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

# SMA crossover strategies live in src/trading_engine/strategies/moving_averages.py.

# STATISTICAL ARBITRAGE STRATEGY ----------------------------------------------------

class PairsTradingStrategy:
    """
    Statistical Arbitrage strategy using Z-Score of the ratio between two symbols.

    The pair comes from 'symbol_a'/'symbol_b' in params, or otherwise from the
    simulator's tracked stocks (the first two, alphabetically). Only symbol A is
    traded, and it is only sold when held (paper trading has no shorting).
    """

    name = "stat_arb_pairs"

    def generate_signals(
        self,
        prices: list[PriceBar],
        portfolio: PortfolioSnapshot,
        params: dict,
    ) -> list[Signal]:
        window = int(params.get("window", 20))
        entry_threshold = Decimal(str(params.get("entry_threshold", "2.0")))
        trade_quantity = Decimal(str(params.get("trade_quantity", "10")))

        # 1. Organize data by symbol
        bars_by_symbol: dict[str, list[PriceBar]] = defaultdict(list)
        for bar in prices:
            bars_by_symbol[bar.symbol.upper()].append(bar)

        created_at = datetime.utcnow()
        tracked = sorted(bars_by_symbol)
        symbol_a = str(params.get("symbol_a") or (tracked[0] if tracked else "")).upper()
        symbol_b = str(params.get("symbol_b") or (tracked[1] if len(tracked) > 1 else "")).upper()
        if not symbol_a:
            return []
        latest_a = self._latest_close(bars_by_symbol.get(symbol_a, []))
        if not symbol_b or symbol_b == symbol_a:
            return [self._hold_signal(
                symbol_a,
                "Pairs trading needs two tracked stocks; add a second stock to form a pair",
                created_at,
                latest_a,
            )]

        # 2. Align and calculate the ratio (Price A / Price B)
        # We need both prices for the same day to calculate a valid ratio
        a_closes = {b.day: b.close for b in bars_by_symbol.get(symbol_a, [])}
        b_closes = {b.day: b.close for b in bars_by_symbol.get(symbol_b, [])}

        common_days = sorted(set(a_closes.keys()) & set(b_closes.keys()))
        ratios = [a_closes[day] / b_closes[day] for day in common_days if b_closes[day]]

        if len(ratios) < window:
            return [self._hold_signal(
                symbol_a,
                f"Insufficient history for {symbol_a}/{symbol_b} ({len(ratios)}/{window} days)",
                created_at,
                latest_a,
            )]

        # 3. Calculate Z-Score
        current_ratio = ratios[-1]
        historical_ratios = ratios[-window:]

        # Convert Decimals to float for standard math lib
        float_ratios = [float(r) for r in historical_ratios]
        avg = mean(float_ratios)
        sd = stdev(float_ratios) if len(float_ratios) > 1 else 0.0
        if sd == 0:
            return [self._hold_signal(
                symbol_a, f"{symbol_a}/{symbol_b} ratio has not varied", created_at, latest_a
            )]
        z_score = (float(current_ratio) - avg) / sd

        # 4. Generate Signals based on Mean Reversion
        # If Z-Score is high, Symbol A is overpriced relative to B -> sell A (if held)
        # If Z-Score is low, Symbol A is underpriced relative to B -> buy A
        pair = f"{symbol_a}/{symbol_b}"
        if z_score > float(entry_threshold):
            position = portfolio.positions.get(symbol_a)
            held = position.quantity if position else Decimal("0")
            if held <= 0:
                return [self._hold_signal(
                    symbol_a,
                    f"{pair} Z-Score {z_score:.2f} > {entry_threshold} but no {symbol_a} position to sell",
                    created_at,
                    latest_a,
                )]
            return [self._create_signal(
                symbol_a, SignalAction.SELL, min(trade_quantity, held),
                f"{pair} Z-Score {z_score:.2f} > {entry_threshold}", created_at, latest_a,
            )]
        if z_score < -float(entry_threshold):
            return [self._create_signal(
                symbol_a, SignalAction.BUY, trade_quantity,
                f"{pair} Z-Score {z_score:.2f} < -{entry_threshold}", created_at, latest_a,
            )]
        return [self._hold_signal(
            symbol_a, f"{pair} Z-Score {z_score:.2f} within neutral band", created_at, latest_a
        )]

    @staticmethod
    def _latest_close(bars: list[PriceBar]) -> Decimal:
        return max(bars, key=lambda bar: bar.day).close if bars else Decimal("0")

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
            # we provide liquidity by SELLING (only shares we hold; no shorting).
            position = portfolio.positions.get(symbol)
            held = position.quantity if position else Decimal("0")
            if price_gap > dev_threshold and held > 0:
                signals.append(Signal(
                    symbol=symbol,
                    action=SignalAction.SELL,
                    quantity=min(trade_size, held),
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