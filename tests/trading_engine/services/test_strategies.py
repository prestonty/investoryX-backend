from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from src.trading_engine.services.actions import SignalAction
from src.trading_engine.services.portfolio import PortfolioSnapshot
from src.trading_engine.services.pricing import PriceBar
from src.trading_engine.services.strategy import PairsTradingStrategy
from src.trading_engine.strategies import Sma50x200CrossoverStrategy

START = date(2024, 1, 1)


def _bars(symbol: str, closes: list[float]) -> list[PriceBar]:
    return [
        PriceBar(symbol, START + timedelta(days=i), Decimal(str(c)), Decimal(str(c)),
                 Decimal(str(c)), Decimal(str(c)), 1000, "yfinance")
        for i, c in enumerate(closes)
    ]


def _portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        user_id=1, cash=Decimal("10000"), positions={}, as_of=datetime.now(timezone.utc)
    )


def test_pairs_buys_when_a_is_cheap() -> None:
    # A/B ratio sits near 1.0 for 19 days, then A drops: z-score far below -2.
    a_dip = [100 + (i % 2) for i in range(19)] + [70]
    prices = _bars("AAA", a_dip) + _bars("BBB", [100] * 20)

    signal, reference = PairsTradingStrategy().generate_signals(prices, _portfolio(), {})

    assert (signal.symbol, signal.action, signal.quantity) == ("AAA", SignalAction.BUY, Decimal("10"))
    assert (reference.symbol, reference.action) == ("BBB", SignalAction.HOLD)


def test_sma_50_200_buys_on_golden_cross() -> None:
    # Flat for 200 days, then a jump lifts the 50-day SMA above the 200-day.
    closes = [100.0] * 200 + [130.0]

    [signal] = Sma50x200CrossoverStrategy().generate_signals(
        _bars("NVDA", closes), _portfolio(), {"trade_quantity": 3}
    )

    assert (signal.action, signal.quantity) == (SignalAction.BUY, Decimal("3"))
