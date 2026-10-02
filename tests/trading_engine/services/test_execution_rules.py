from __future__ import annotations

from decimal import Decimal

from src.trading_engine.services.actions import SignalAction
from src.trading_engine.services.execution import (
    ExecutionRules,
    Fill,
    FillRejected,
    plan_fill,
)


def _buy(quantity: str, rules: ExecutionRules, cash: str = "10000", held: str = "0",
         equity: str = "10000", price: str = "100") -> Fill | FillRejected:
    return plan_fill(
        side=SignalAction.BUY,
        quantity=Decimal(quantity),
        market_price=Decimal(price),
        cash=Decimal(cash),
        held_shares=Decimal(held),
        equity=Decimal(equity),
        rules=rules,
    )


def test_no_rules_fills_full_quantity_at_market() -> None:
    fill = _buy("5", ExecutionRules())

    assert isinstance(fill, Fill)
    assert (fill.quantity, fill.price, fill.limited_by) == (Decimal("5"), Decimal("100"), None)
    assert fill.cash_delta == Decimal("-500")


def test_max_order_value_shrinks_buy() -> None:
    fill = _buy("10", ExecutionRules(max_order_value=Decimal("350")))

    assert (fill.quantity, fill.requested_quantity) == (Decimal("3"), Decimal("10"))
    assert fill.limited_by == "max_order_value"


def test_tightest_cap_wins() -> None:
    rules = ExecutionRules(max_order_value=Decimal("500"), max_position_pct=Decimal("2"))

    fill = _buy("10", rules)  # 2% of 10000 = $200 -> 2 shares

    assert (fill.quantity, fill.limited_by) == (Decimal("2"), "max_position_pct")


def test_cap_leaving_no_whole_share_rejects() -> None:
    result = _buy("1", ExecutionRules(max_order_value=Decimal("50")))

    assert result == FillRejected("exceeds max_order_value")


def test_cash_check_uses_slipped_price_and_fee() -> None:
    rules = ExecutionRules(fee_per_trade=Decimal("1"), slippage_bps=Decimal("100"))

    # 2 x $101 + $1 fee = $203 > $202 cash
    assert _buy("2", rules, cash="202") == FillRejected("insufficient cash")
    assert isinstance(_buy("2", rules, cash="203"), Fill)


def test_sell_is_not_capped_but_needs_shares() -> None:
    rules = ExecutionRules(max_position_pct=Decimal("1"), max_order_value=Decimal("1"))

    def sell(quantity: str) -> Fill | FillRejected:
        return plan_fill(
            side=SignalAction.SELL,
            quantity=Decimal(quantity),
            market_price=Decimal("100"),
            cash=Decimal("0"),
            held_shares=Decimal("3"),
            equity=Decimal("300"),
            rules=rules,
        )

    assert sell("3").quantity == Decimal("3")
    assert sell("4") == FillRejected("insufficient shares")


def test_rules_for_simulator_read_its_risk_limit() -> None:
    class _Simulator:
        max_position_pct = Decimal("20.00")

    rules = ExecutionRules.for_simulator(
        _Simulator(), fee_per_trade=Decimal("2"), slippage_bps=Decimal("5")
    )

    assert rules.max_position_pct == Decimal("20.00")
    assert (rules.fee_per_trade, rules.slippage_bps) == (Decimal("2"), Decimal("5"))
