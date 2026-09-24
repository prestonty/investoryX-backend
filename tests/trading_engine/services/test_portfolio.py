from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.models.simulator import Simulator
from src.models.simulator_position import SimulatorPosition
from src.models.simulator_trade import SimulatorTrade
from src.trading_engine.services.actions import SignalAction
from src.trading_engine.services.portfolio import ExecutedTrade, PortfolioService


def _trade(
    trade_id: int,
    side: SignalAction,
    quantity: str,
    price: str,
    fee: str = "0",
    symbol: str = "AAPL",
) -> ExecutedTrade:
    return ExecutedTrade(
        trade_id=trade_id,
        simulator_id=1,
        symbol=symbol,
        side=side,
        quantity=Decimal(quantity),
        price=Decimal(price),
        fee=Decimal(fee),
        executed_at=datetime.now(timezone.utc),
    )


def test_replay_trades_buy_sell_and_avg_cost() -> None:
    service = PortfolioService()
    trades = [
        _trade(1, SignalAction.BUY, "2", "100", "1"),
        _trade(2, SignalAction.BUY, "1", "130", "1"),
        _trade(3, SignalAction.SELL, "1", "150", "1"),
    ]

    cash, positions = service._replay_trades(Decimal("1000"), trades)

    assert cash == Decimal("817")
    assert set(positions.keys()) == {"AAPL"}
    assert positions["AAPL"].quantity == Decimal("2")
    assert positions["AAPL"].average_cost == (Decimal("332") / Decimal("3"))


def test_replay_trades_removes_position_when_quantity_hits_zero() -> None:
    service = PortfolioService()
    trades = [
        _trade(1, SignalAction.BUY, "1", "100"),
        _trade(2, SignalAction.SELL, "1", "110"),
    ]

    cash, positions = service._replay_trades(Decimal("500"), trades)

    assert cash == Decimal("510")
    assert positions == {}


def test_replay_trades_raises_when_selling_more_than_held() -> None:
    service = PortfolioService()
    trades = [_trade(1, SignalAction.SELL, "1", "100")]

    with pytest.raises(ValueError, match="sells"):
        service._replay_trades(Decimal("500"), trades)


def _db_trade(simulator_id: int, side: str, shares: str, price: str, source: str | None):
    return SimulatorTrade(
        simulator_id=simulator_id,
        ticker="AAPL",
        side=side,
        price=Decimal(price),
        shares=Decimal(shares),
        fee=Decimal("0"),
        executed_at=datetime(2024, 3, 8, 21, tzinfo=timezone.utc),
        source=source,
    )


def test_reconcile_ignores_backtest_trades(db) -> None:
    db.simulator(1, cash="1000")
    db.add(
        _db_trade(1, "buy", "2", "100", "live"),
        _db_trade(1, "buy", "1", "50", None),  # pre-`source` rows count as live
        _db_trade(1, "buy", "5", "100", "backtest"),
    )

    with db.session() as session:
        result = PortfolioService().reconcile_simulator(session, 1)
        session.commit()

    assert result.trades_processed == 2
    assert db.get(Simulator, 1).cash_balance == Decimal("750")
    positions = db.all(SimulatorPosition, simulator_id=1)
    assert [(p.ticker, p.shares) for p in positions] == [("AAPL", Decimal("3"))]


def test_reconcile_all_isolates_failing_simulator(db) -> None:
    db.simulator(1, cash="1000")
    db.simulator(2, user_id=None, cash="1000")  # get_snapshot rejects a missing user
    db.simulator(3, cash="1000")
    db.add(_db_trade(1, "buy", "1", "100", "live"), _db_trade(3, "buy", "2", "100", "live"))

    with db.session() as session:
        results, failures = PortfolioService().reconcile_all(session)
        session.commit()

    assert [r.simulator_id for r in results] == [1, 3]
    assert [f["simulator_id"] for f in failures] == [2]
    assert db.get(Simulator, 1).cash_balance == Decimal("900")
    assert db.get(Simulator, 3).cash_balance == Decimal("800")
