from __future__ import annotations

from decimal import Decimal

from src.trading_engine.services.actions import SignalAction
from src.trading_engine.services.execution import ExecutionRules, plan_fill


def _buy(quantity: str, rules: ExecutionRules):
    return plan_fill(
        side=SignalAction.BUY,
        quantity=Decimal(quantity),
        market_price=Decimal("100"),
        cash=Decimal("10000"),
        held_shares=Decimal("0"),
        equity=Decimal("10000"),
        rules=rules,
    )


def test_buy_fills_with_fee_and_slippage() -> None:
    fill = _buy("5", ExecutionRules(fee_per_trade=Decimal("1"), slippage_bps=Decimal("100")))

    assert (fill.quantity, fill.price) == (Decimal("5"), Decimal("101"))
    assert fill.cash_delta == Decimal("-506")


def test_max_position_pct_shrinks_buy_to_whole_shares() -> None:
    # 25% of $10,000 equity = $2,500 -> 25 shares at $100.
    fill = _buy("40", ExecutionRules(max_position_pct=Decimal("25")))

    assert (fill.quantity, fill.limited_by) == (Decimal("25"), "max_position_pct")
