from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

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
