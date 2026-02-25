from __future__ import annotations

from decimal import Decimal

import pytest

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

    execute_module.execute_signals(slippage_bps="12.5", fee_per_trade="1.25")

    assert captured["session"] is session
    assert captured["slippage_bps"] == Decimal("12.5")
    assert captured["fee_per_trade"] == Decimal("1.25")
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
