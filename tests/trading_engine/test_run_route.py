from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import src.routes.simulator as simulator_routes
from src.core.database import get_db
from src.core.security import get_current_active_user
from src.main import app
from src.models.simulator import SIMULATOR_STATUS_PAUSED
from src.models.users import Users
from src.trading_engine.tasks.daily_pipeline import MissingPriceDataError


@pytest.fixture
def client(db):
    def _get_db():
        with db.session() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_active_user] = lambda: Users(user_id=1)
    yield TestClient(app)
    app.dependency_overrides.clear()


def _pipeline_result(status: str, executed: int = 0) -> dict:
    return {
        "day": "2024-03-08",
        "signals": {"simulator_results": [{"simulator_id": 1, "status": status}]},
        "trades_executed": {"executed": executed},
    }


def test_run_uses_engine_pipeline_for_that_simulator(db, client, monkeypatch) -> None:
    db.simulator(1)
    calls: list = []

    def _run_pipeline(simulator_id):
        calls.append(simulator_id)
        return _pipeline_result("ok", executed=2)

    monkeypatch.setattr(simulator_routes, "run_pipeline", _run_pipeline)

    response = client.post("/api/simulator/1/run", json={})

    assert response.status_code == 200
    assert calls == [1]
    body = response.json()
    assert body["message"] == "Simulator run completed"
    assert body["trades_executed"] == 2
    assert Decimal(str(body["cash_balance"])) == Decimal("1000")


def test_run_reports_already_evaluated(db, client, monkeypatch) -> None:
    db.simulator(1)
    monkeypatch.setattr(
        simulator_routes,
        "run_pipeline",
        lambda simulator_id: _pipeline_result("skipped_already_evaluated"),
    )

    response = client.post("/api/simulator/1/run", json={})

    assert response.json()["message"] == "Already evaluated for 2024-03-08"


def test_run_skips_paused_simulator(db, client, monkeypatch) -> None:
    db.simulator(1, status=SIMULATOR_STATUS_PAUSED)
    monkeypatch.setattr(simulator_routes, "run_pipeline", pytest.fail)

    response = client.post("/api/simulator/1/run", json={})

    assert response.json()["message"] == "Simulator is paused"


def test_run_returns_503_without_prices(db, client, monkeypatch) -> None:
    db.simulator(1)

    def _missing(simulator_id):
        raise MissingPriceDataError("no bars")

    monkeypatch.setattr(simulator_routes, "run_pipeline", _missing)

    response = client.post("/api/simulator/1/run", json={})

    assert response.status_code == 503
