from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

import src.trading_engine.services.manual_orders as manual_orders
from src.core.config import settings
from src.models.simulator import Simulator
from src.models.simulator_order import SimulatorOrder
from src.models.simulator_position import SimulatorPosition
from src.models.simulator_signal import SimulatorSignal
from src.models.simulator_trade import SimulatorTrade
from src.trading_engine.services.actions import SignalAction
from src.trading_engine.services.evaluation import EvaluationService
from src.trading_engine.services.manual_orders import (
    ManualOrderService,
    OrderRejected,
    switch_trading_mode,
)
from src.trading_engine.services.pricing import MARKET_TZ, PriceBar

FRIDAY_MIDDAY = datetime(2024, 3, 8, 11, 0, tzinfo=MARKET_TZ)  # market open
FRIDAY_EVENING = datetime(2024, 3, 8, 18, 0, tzinfo=MARKET_TZ)  # closed: next open is Monday
MONDAY = date(2024, 3, 11)
MONDAY_PREMARKET = datetime(2024, 3, 11, 9, 0, tzinfo=MARKET_TZ)
MONDAY_AFTER_OPEN = datetime(2024, 3, 11, 9, 40, tzinfo=MARKET_TZ)


class FakeMarket:
    """Yahoo stand-in: each test sets the latest prices and the opens Yahoo knows."""

    def __init__(self) -> None:
        self.last: dict[str, Decimal] = {"AAPL": Decimal("100")}
        self.opens: dict[tuple[str, date], Decimal] = {}


@pytest.fixture
def market(monkeypatch) -> FakeMarket:
    fake = FakeMarket()

    class _Yahoo:
        def fetch_daily_bars(self, symbols, day):
            return [
                PriceBar(symbol, day, price, price, price, price, 0, "yfinance")
                for symbol in symbols
                if (price := fake.opens.get((symbol, day))) is not None
            ]

    monkeypatch.setattr(manual_orders, "fetch_last_price", lambda symbol: fake.last.get(symbol))
    monkeypatch.setattr(manual_orders, "YahooPriceProvider", _Yahoo)
    # 10 bps = 0.1%, so a $100 buy fills at $100.10 and a sell at $99.90.
    monkeypatch.setattr(settings, "sim_slippage_bps", Decimal("10"))
    monkeypatch.setattr(settings, "sim_fee_per_trade", Decimal("1"))
    monkeypatch.setattr(settings, "sim_max_order_value", None)
    return fake


def _place(db, side: str, shares: int, now: datetime, ticker: str = "AAPL"):
    with db.session() as session:
        placed = ManualOrderService().place(
            session, 1, ticker, SignalAction(side), Decimal(shares), now=now
        )
        session.commit()
        return placed


def _fill_due(db, now: datetime):
    with db.session() as session:
        return ManualOrderService().fill_due_orders(session, now=now)


def _cash(db) -> Decimal:
    return Decimal(str(db.get(Simulator, 1).cash_balance))


def test_buy_and_sell_fill_immediately_with_slippage_against_the_user(db, market) -> None:
    db.simulator(1, cash="10000", strategy_name="manual")

    bought = _place(db, "buy", 5, FRIDAY_MIDDAY)
    assert bought.order is None
    assert (bought.trade.price, bought.trade.source) == (Decimal("100.1"), "manual")
    # 5 x $100.10 + $1 fee
    assert _cash(db) == Decimal("9498.50")
    [position] = db.all(SimulatorPosition, simulator_id=1)
    assert (Decimal(str(position.shares)), Decimal(str(position.avg_cost))) == (
        Decimal("5"), Decimal("100.3"),
    )

    market.last["AAPL"] = Decimal("110")
    sold = _place(db, "sell", 2, FRIDAY_MIDDAY)
    assert sold.trade.price == Decimal("109.89")
    # + 2 x $109.89 - $1 fee
    assert _cash(db) == Decimal("9717.28")


def test_order_after_the_close_fills_at_the_next_open(db, market) -> None:
    db.simulator(1, cash="10000", strategy_name="manual")

    queued = _place(db, "buy", 5, FRIDAY_EVENING)
    assert queued.trade is None
    assert (queued.quote.fills_now, queued.quote.fill_day) == (False, MONDAY)
    assert queued.order.status == "pending"
    assert _cash(db) == Decimal("10000")

    # Not before Monday's open.
    assert _fill_due(db, MONDAY_PREMARKET).filled == 0

    db.bars("AAPL", [MONDAY], "90")  # Monday opens at $90
    assert _fill_due(db, MONDAY_AFTER_OPEN).filled == 1

    [order] = db.all(SimulatorOrder, simulator_id=1)
    [trade] = db.all(SimulatorTrade, simulator_id=1)
    assert (order.status, order.trade_id) == ("filled", trade.trade_id)
    assert Decimal(str(trade.price)) == Decimal("90.09")
    assert _cash(db) == Decimal("9548.55")


def test_waits_for_the_opening_price_then_gives_up(db, market) -> None:
    db.simulator(1, cash="10000", strategy_name="manual")
    _place(db, "buy", 5, FRIDAY_EVENING)

    assert _fill_due(db, MONDAY_AFTER_OPEN).waiting == 1

    later = datetime(2024, 3, 18, 10, 0, tzinfo=MARKET_TZ)
    assert _fill_due(db, later).rejected == 1
    [order] = db.all(SimulatorOrder, simulator_id=1)
    assert (order.status, order.error) == ("rejected", "No opening price for AAPL on 2024-03-11")


def test_opening_price_can_come_from_yahoo(db, market) -> None:
    db.simulator(1, cash="10000", strategy_name="manual")
    _place(db, "buy", 5, FRIDAY_EVENING)
    market.opens[("AAPL", MONDAY)] = Decimal("90")

    assert _fill_due(db, MONDAY_AFTER_OPEN).filled == 1


def test_queued_buys_set_cash_aside(db, market) -> None:
    db.simulator(1, cash="1000", strategy_name="manual")
    _place(db, "buy", 6, FRIDAY_EVENING)  # about $601.60

    with pytest.raises(OrderRejected) as rejected:
        _place(db, "buy", 4, FRIDAY_EVENING)
    assert str(rejected.value) == (
        "Not enough cash: this order needs about $401.40, and $398.40 is available "
        "(some is set aside for your queued orders)"
    )


def test_queued_orders_fill_in_order_and_reject_what_no_longer_fits(db, market) -> None:
    db.simulator(1, cash="1000", strategy_name="manual")
    _place(db, "buy", 5, FRIDAY_EVENING)
    _place(db, "buy", 4, FRIDAY_EVENING)
    db.bars("AAPL", [MONDAY], "120")  # gaps up: only the first still fits

    summary = _fill_due(db, MONDAY_AFTER_OPEN)

    assert (summary.filled, summary.rejected) == (1, 1)
    first, second = sorted(db.all(SimulatorOrder, simulator_id=1), key=lambda o: o.order_id)
    assert (first.status, second.status) == ("filled", "rejected")
    assert second.error.startswith("Not filled at the open: Not enough cash")


def test_cannot_sell_shares_not_owned(db, market) -> None:
    db.simulator(1, cash="1000", strategy_name="manual")

    with pytest.raises(OrderRejected, match="You don't own any AAPL shares"):
        _place(db, "sell", 1, FRIDAY_MIDDAY)


def test_risk_limit_rejects_rather_than_shrinking_the_order(db, market) -> None:
    db.simulator(1, cash="10000", strategy_name="manual")
    with db.session() as session:
        session.get(Simulator, 1).max_position_pct = Decimal("25")
        session.commit()

    # 25% of $10,000 = $2,500, which buys 24 shares at $100.10.
    with pytest.raises(OrderRejected) as rejected:
        _place(db, "buy", 40, FRIDAY_MIDDAY)
    assert str(rejected.value) == (
        "Your max position size is 25% of the portfolio: you can buy at most 24 more AAPL shares"
    )
    assert db.all(SimulatorTrade, simulator_id=1) == []


def test_orders_need_a_manual_simulator(db, market) -> None:
    db.simulator(1, cash="1000", strategy_name="sma_crossover")

    with pytest.raises(OrderRejected, match="Switch its strategy to Manual trading"):
        _place(db, "buy", 1, FRIDAY_MIDDAY)


def test_cancel_a_queued_order(db, market) -> None:
    db.simulator(1, cash="1000", strategy_name="manual")
    order_id = _place(db, "buy", 1, FRIDAY_EVENING).order.order_id

    with db.session() as session:
        ManualOrderService().cancel(session, 1, order_id, now=FRIDAY_EVENING)
        session.commit()
        with pytest.raises(OrderRejected, match="already cancelled"):
            ManualOrderService().cancel(session, 1, order_id, now=FRIDAY_EVENING)

    assert _fill_due(db, MONDAY_AFTER_OPEN).filled == 0


def test_switching_modes_cancels_the_other_modes_queued_orders(db, market) -> None:
    db.simulator(1, cash="1000", strategy_name="sma_crossover")
    db.add(
        SimulatorSignal(
            simulator_id=1, ticker="AAPL", action="buy", quantity=Decimal("1"),
            reason="dip", confidence=Decimal("0.7"), strategy_name="sma_crossover",
            status="pending", for_day=date(2024, 3, 7),
        )
    )

    with db.session() as session:
        switch_trading_mode(session, 1, "sma_crossover", "manual", now=FRIDAY_EVENING)
        session.get(Simulator, 1).strategy_name = "manual"
        session.commit()
    [signal] = db.all(SimulatorSignal, simulator_id=1)
    assert (signal.status, signal.execution_error) == (
        "skipped", "cancelled: switched to manual trading",
    )

    _place(db, "buy", 1, FRIDAY_EVENING)
    with db.session() as session:
        switch_trading_mode(session, 1, "manual", "sma_crossover", now=FRIDAY_EVENING)
        session.commit()
    [order] = db.all(SimulatorOrder, simulator_id=1)
    assert (order.status, order.error) == ("cancelled", "Cancelled: switched to automated trading")


def test_strategy_evaluation_skips_manual_simulators(db) -> None:
    db.simulator(1, strategy_name="manual")
    db.simulator(2, strategy_name="sma_crossover")

    targets = EvaluationService().load_target_portfolios()

    assert [int(sim.simulator_id) for sim in targets] == [2]
