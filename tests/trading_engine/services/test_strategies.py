from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from src.trading_engine.services.actions import SignalAction
from src.trading_engine.services.portfolio import PortfolioSnapshot, Position
from src.trading_engine.services.pricing import PriceBar
from src.trading_engine.services.strategy import AuctionLiquidityStrategy, PairsTradingStrategy
from src.trading_engine.strategies import Sma50x200CrossoverStrategy

START = date(2024, 1, 1)


def _bars(symbol: str, closes: list[float]) -> list[PriceBar]:
    return [
        PriceBar(symbol, START + timedelta(days=i), Decimal(str(c)), Decimal(str(c)),
                 Decimal(str(c)), Decimal(str(c)), 1000, "yfinance")
        for i, c in enumerate(closes)
    ]


def _portfolio(**held: str) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        user_id=1,
        cash=Decimal("10000"),
        positions={s: Position(s, Decimal(q), Decimal("1")) for s, q in held.items()},
        as_of=datetime.now(timezone.utc),
    )


# A/B ratio sits near 1.0 for 19 days, then A jumps: z-score far above 2.
_A_SPIKE = [100 + (i % 2) for i in range(19)] + [130]
_A_DIP = [100 + (i % 2) for i in range(19)] + [70]
_B_FLAT = [100] * 20


def test_pairs_uses_tracked_stocks_not_pep_ko() -> None:
    prices = _bars("NVDA", _A_DIP) + _bars("AMD", _B_FLAT)

    [signal] = PairsTradingStrategy().generate_signals(prices, _portfolio(), {})

    # Alphabetical: AMD is symbol A, NVDA is symbol B. NVDA dipping makes AMD/NVDA spike.
    assert signal.symbol == "AMD"
    assert "AMD/NVDA" in signal.reason


def test_pairs_with_one_tracked_stock_holds_with_reason() -> None:
    [signal] = PairsTradingStrategy().generate_signals(_bars("NVDA", _B_FLAT), _portfolio(), {})

    assert (signal.symbol, signal.action) == ("NVDA", SignalAction.HOLD)
    assert "two tracked stocks" in signal.reason
    assert signal.price == Decimal("100")


def test_pairs_buys_when_a_is_cheap() -> None:
    prices = _bars("AAA", _A_DIP) + _bars("BBB", _B_FLAT)

    [signal] = PairsTradingStrategy().generate_signals(prices, _portfolio(), {})

    assert (signal.symbol, signal.action, signal.quantity) == ("AAA", SignalAction.BUY, Decimal("10"))
    assert signal.price == Decimal("70")


def test_pairs_only_sells_what_is_held() -> None:
    prices = _bars("AAA", _A_SPIKE) + _bars("BBB", _B_FLAT)
    strategy = PairsTradingStrategy()

    [no_position] = strategy.generate_signals(prices, _portfolio(), {})
    [partial] = strategy.generate_signals(prices, _portfolio(AAA="4"), {})

    assert no_position.action == SignalAction.HOLD
    assert "no AAA position" in no_position.reason
    assert (partial.action, partial.quantity) == (SignalAction.SELL, Decimal("4"))


def test_pairs_constant_ratio_does_not_crash() -> None:
    prices = _bars("AAA", _B_FLAT) + _bars("BBB", _B_FLAT)

    [signal] = PairsTradingStrategy().generate_signals(prices, _portfolio(), {})

    assert signal.action == SignalAction.HOLD


def test_pairs_explicit_params_still_win() -> None:
    prices = _bars("AAA", _A_DIP) + _bars("BBB", _B_FLAT) + _bars("CCC", _B_FLAT)

    [signal] = PairsTradingStrategy().generate_signals(
        prices, _portfolio(), {"symbol_a": "ccc", "symbol_b": "bbb"}
    )

    assert signal.symbol == "CCC"


def test_auction_sell_is_capped_to_held_shares() -> None:
    spike = _bars("NVDA", [100, 100, 100, 100, 130])
    strategy = AuctionLiquidityStrategy()

    assert strategy.generate_signals(spike, _portfolio(), {}) == []
    [signal] = strategy.generate_signals(spike, _portfolio(NVDA="7"), {})
    assert (signal.action, signal.quantity) == (SignalAction.SELL, Decimal("7"))


def test_sma_50_200_generates_signals_without_crashing() -> None:
    closes = [100.0] * 200 + [90.0] * 10 + [130.0] * 40
    signals = Sma50x200CrossoverStrategy().generate_signals(_bars("NVDA", closes), _portfolio(), {})

    assert len(signals) == 1 and signals[0].price == Decimal("130")
