from __future__ import annotations

import pytest

import src.trading_engine.tasks.reconcile_portfolios as reconcile_module


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


class _FakeResult:
    def __init__(self, simulator_id: int) -> None:
        self.simulator_id = simulator_id

    def to_dict(self) -> dict:
        return {"simulator_id": self.simulator_id}


def test_reconcile_single_simulator(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession()

    class _Service:
        def reconcile_simulator(self, session: _FakeSession, simulator_id: int) -> _FakeResult:
            return _FakeResult(simulator_id)

    monkeypatch.setattr(reconcile_module, "SessionLocal", lambda: session)
    monkeypatch.setattr(reconcile_module, "PortfolioService", lambda: _Service())

    result = reconcile_module.reconcile_portfolios(simulator_id=7)

    assert result == {
        "simulator_id": 7,
        "reconciled": 1,
        "results": [{"simulator_id": 7}],
    }
    assert session.committed is True
    assert session.rolled_back is False
    assert session.closed is True


def test_reconcile_all_simulators(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession()

    class _Service:
        def reconcile_all(self, session: _FakeSession, limit: int) -> list[_FakeResult]:
            return [_FakeResult(1), _FakeResult(2)]

    monkeypatch.setattr(reconcile_module, "SessionLocal", lambda: session)
    monkeypatch.setattr(reconcile_module, "PortfolioService", lambda: _Service())

    result = reconcile_module.reconcile_portfolios(limit=100)

    assert result == {
        "simulator_id": None,
        "reconciled": 2,
        "results": [{"simulator_id": 1}, {"simulator_id": 2}],
    }
    assert session.committed is True
    assert session.rolled_back is False
    assert session.closed is True


def test_reconcile_rolls_back_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession()

    class _Service:
        def reconcile_all(self, session: _FakeSession, limit: int) -> list[_FakeResult]:
            raise RuntimeError("boom")

    monkeypatch.setattr(reconcile_module, "SessionLocal", lambda: session)
    monkeypatch.setattr(reconcile_module, "PortfolioService", lambda: _Service())

    with pytest.raises(RuntimeError, match="boom"):
        reconcile_module.reconcile_portfolios(limit=10)

    assert session.committed is False
    assert session.rolled_back is True
    assert session.closed is True
