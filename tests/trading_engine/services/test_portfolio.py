from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from src.trading_engine.services.actions import SignalAction
from src.trading_engine.services.portfolio import ExecutedTrade, PortfolioService


def _trade(trade_id: int, side: SignalAction, quantity: str, price: str) -> ExecutedTrade:
    return ExecutedTrade(
        trade_id=trade_id,
        simulator_id=1,
        symbol="AAPL",
        side=side,
        quantity=Decimal(quantity),
        price=Decimal(price),
        fee=Decimal("1"),
        executed_at=datetime.now(timezone.utc),
    )


def test_replay_trades_rebuilds_cash_and_average_cost() -> None:
    trades = [
        _trade(1, SignalAction.BUY, "2", "100"),
        _trade(2, SignalAction.BUY, "1", "130"),
        _trade(3, SignalAction.SELL, "1", "150"),
    ]

    cash, positions = PortfolioService()._replay_trades(Decimal("1000"), trades)

    assert cash == Decimal("817")
    assert positions["AAPL"].quantity == Decimal("2")
    assert positions["AAPL"].average_cost == Decimal("332") / Decimal("3")
