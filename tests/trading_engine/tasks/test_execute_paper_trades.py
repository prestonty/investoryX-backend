from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.models.price_bar import PriceBar
from src.models.simulator_cash_ledger import SimulatorCashLedger
from src.models.simulator_position import SimulatorPosition
from src.models.simulator_signal import SimulatorSignal
from src.models.simulator_trade import SimulatorTrade
from src.trading_engine.services.execution import ExecutionSummary
import src.trading_engine.tasks.execute_paper_trades as execute_module


class _FakeSession:
    def __init__(self) -> None:
        self.rolled_back = False
        self.closed = False

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def test_record_paper_trades_returns_json_safe_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = ExecutionSummary(
        processed=3,
        executed=2,
        skipped=1,
        failed=0,
        trades_created=2,
    )
    monkeypatch.setattr(execute_module, "execute_signals", lambda **_: summary)

    result = execute_module.record_paper_trades()

    assert result == {
        "processed": 3,
        "executed": 2,
        "skipped": 1,
        "failed": 0,
        "trades_created": 2,
    }


def test_execute_signals_normalizes_decimals_and_closes_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    captured: dict = {}

    class _Service:
        def execute_pending_signals(self, **kwargs) -> ExecutionSummary:
            captured.update(kwargs)
            return ExecutionSummary(0, 0, 0, 0, 0)

    monkeypatch.setattr(execute_module, "SessionLocal", lambda: session)
    monkeypatch.setattr(execute_module, "PaperTradeExecutionService", lambda: _Service())

    execute_module.execute_signals(slippage_bps="12.5", fee_per_trade="1.25", day="2024-03-08")

    assert captured["session"] is session
    assert captured["slippage_bps"] == Decimal("12.5")
    assert captured["fee_per_trade"] == Decimal("1.25")
    assert captured["trade_day"] == date(2024, 3, 8)
    assert session.rolled_back is False
    assert session.closed is True


def test_execute_signals_rolls_back_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession()

    class _Service:
        def execute_pending_signals(self, **kwargs) -> ExecutionSummary:
            raise RuntimeError("explode")

    monkeypatch.setattr(execute_module, "SessionLocal", lambda: session)
    monkeypatch.setattr(execute_module, "PaperTradeExecutionService", lambda: _Service())

    with pytest.raises(RuntimeError, match="explode"):
        execute_module.execute_signals()

    assert session.rolled_back is True
    assert session.closed is True


TRADE_DAY = date(2024, 3, 8)  # Friday
SIGNAL_DAY = date(2024, 3, 7)  # previous trading day: its close decided the order


def _pending_buy(
    simulator_id: int = 1,
    for_day: date | None = SIGNAL_DAY,
    quantity: str = "2",
) -> SimulatorSignal:
    return SimulatorSignal(
        simulator_id=simulator_id,
        ticker="AAPL",
        action="buy",
        quantity=Decimal(quantity),
        reason="test",
        confidence=Decimal("1"),
        strategy_name="sma_crossover",
        status="pending",
        for_day=for_day,
    )


def test_signal_fails_without_bar_for_trade_day(db) -> None:
    db.simulator(1)
    db.bars("AAPL", [SIGNAL_DAY])  # only the decision day's price, nothing to fill at
    db.add(_pending_buy())

    summary = execute_module.execute_signals(day=TRADE_DAY)

    assert summary.failed == 1 and summary.trades_created == 0
    [signal] = db.all(SimulatorSignal)
    assert signal.status == "failed"
    assert "on 2024-03-08" in signal.execution_error
    assert db.all(SimulatorTrade) == []


def test_executed_trade_writes_ledger_row(db) -> None:
    db.simulator(1, cash="1000")
    db.bars("AAPL", [TRADE_DAY], close="100")
    db.add(_pending_buy())

    summary = execute_module.execute_signals(day=TRADE_DAY, fee_per_trade="1")

    assert summary.executed == 1
    [trade] = db.all(SimulatorTrade)
    assert (trade.price, trade.shares, trade.source) == (Decimal("100"), Decimal("2"), "live")
    [ledger] = db.all(SimulatorCashLedger)
    assert ledger.delta == Decimal("-201")
    assert ledger.balance_after == Decimal("799")
    assert (ledger.reason, ledger.source) == ("buy", "live")


@pytest.mark.parametrize("for_day", [SIGNAL_DAY - timedelta(days=1), None])
def test_stale_or_undated_signal_expires_instead_of_filling(db, for_day) -> None:
    db.simulator(1, cash="1000")
    db.bars("AAPL", [SIGNAL_DAY, TRADE_DAY], close="100")
    db.add(_pending_buy(for_day=for_day))  # e.g. left pending by a failed run

    summary = execute_module.execute_signals(day=TRADE_DAY)

    assert (summary.skipped, summary.executed) == (1, 0)
    [signal] = db.all(SimulatorSignal)
    assert signal.status == "skipped"
    assert signal.execution_error.startswith("expired")
    assert db.all(SimulatorTrade) == []


def test_fills_at_trade_day_open_not_close(db) -> None:
    db.simulator(1, cash="1000")
    db.add(PriceBar(
        symbol="AAPL", day=TRADE_DAY, open=Decimal("90"), high=Decimal("110"),
        low=Decimal("85"), close=Decimal("105"), volume=1000, source="yfinance",
    ))
    db.add(_pending_buy())

    execute_module.execute_signals(day=TRADE_DAY)

    [trade] = db.all(SimulatorTrade)
    assert trade.price == Decimal("90")


def test_signal_from_trade_day_waits_for_next_open(db) -> None:
    db.simulator(1, cash="1000")
    db.bars("AAPL", [TRADE_DAY], close="100")
    db.add(_pending_buy(for_day=TRADE_DAY))  # decided on today's close

    summary = execute_module.execute_signals(day=TRADE_DAY)

    assert summary.processed == 0
    [signal] = db.all(SimulatorSignal)
    assert signal.status == "pending"


def test_max_position_pct_shrinks_buy_to_whole_shares(db) -> None:
    # Equity 1000, cap 25% -> at most $250 in AAPL -> 2 shares at $100.
    db.simulator(1, cash="1000", max_position_pct="25")
    db.bars("AAPL", [TRADE_DAY], close="100")
    db.add(_pending_buy(quantity="5"))

    summary = execute_module.execute_signals(day=TRADE_DAY)

    assert summary.executed == 1
    [trade] = db.all(SimulatorTrade)
    assert trade.shares == Decimal("2")


def test_max_position_pct_counts_shares_already_held(db) -> None:
    # Already 2 x $100 of a 1200 equity portfolio; 25% cap leaves $100 -> 1 share.
    db.simulator(1, cash="1000", max_position_pct="25")
    db.add(SimulatorPosition(
        simulator_id=1, ticker="AAPL", shares=Decimal("2"), avg_cost=Decimal("100"),
    ))
    db.bars("AAPL", [TRADE_DAY], close="100")
    db.add(_pending_buy(quantity="5"))

    execute_module.execute_signals(day=TRADE_DAY)

    [trade] = db.all(SimulatorTrade)
    assert trade.shares == Decimal("1")


def test_buy_fails_when_position_is_already_at_cap(db) -> None:
    db.simulator(1, cash="300", max_position_pct="25")
    db.add(SimulatorPosition(
        simulator_id=1, ticker="AAPL", shares=Decimal("1"), avg_cost=Decimal("100"),
    ))
    db.bars("AAPL", [TRADE_DAY], close="100")
    db.add(_pending_buy())

    summary = execute_module.execute_signals(day=TRADE_DAY)

    assert summary.failed == 1
    [signal] = db.all(SimulatorSignal)
    assert signal.execution_error == "exceeds max_position_pct"
