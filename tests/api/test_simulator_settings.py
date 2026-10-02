from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.core.database import get_db
from src.core.security import get_current_active_user
from src.main import app
from src.models.simulator import Simulator
from src.models.users import Users


@pytest.fixture
def client(db):
    def _get_db():
        with db.session() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_active_user] = lambda: Users(user_id=1)
    yield TestClient(app)
    app.dependency_overrides.clear()


def _patch(client: TestClient, payload: dict):
    return client.patch("/api/simulator/1/settings", json=payload)


def test_strategies_endpoint_lists_catalog_with_params(client) -> None:
    response = client.get("/api/strategies")

    assert response.status_code == 200
    by_value = {option["value"]: option for option in response.json()}
    assert "sma_50_200_crossover" in by_value
    assert [p["name"] for p in by_value["sma_50_200_crossover"]["params"]] == [
        "trade_quantity"
    ]


def test_golden_cross_strategy_can_be_selected(db, client) -> None:
    db.simulator(1)

    response = _patch(client, {"strategy_name": "sma_50_200_crossover"})

    assert response.status_code == 200
    assert response.json()["strategy_name"] == "sma_50_200_crossover"


def test_unknown_strategy_is_rejected(db, client) -> None:
    db.simulator(1)

    assert _patch(client, {"strategy_name": "yolo"}).status_code == 422


def test_saves_only_given_params_and_returns_effective_ones(db, client) -> None:
    db.simulator(1)

    response = _patch(client, {"strategy_params": {"short_window": 10, "trade_quantity": 2.5}})

    assert response.status_code == 200
    assert response.json()["strategy_params"] == {
        "short_window": 10,
        "long_window": 20,
        "trade_quantity": 2.5,
    }
    assert db.get(Simulator, 1).strategy_params == {"short_window": 10, "trade_quantity": 2.5}


def test_invalid_params_return_400_and_change_nothing(db, client) -> None:
    db.simulator(1, strategy_params={"short_window": 3})

    response = _patch(client, {"strategy_params": {"short_window": 30}})

    assert response.status_code == 400
    assert "short_window must be smaller than long_window" in response.json()["detail"]
    assert db.get(Simulator, 1).strategy_params == {"short_window": 3}


def test_switching_strategy_resets_params_to_new_defaults(db, client) -> None:
    db.simulator(1, strategy_params={"short_window": 3})

    response = _patch(client, {"strategy_name": "auction_liquidity_provider"})

    assert response.json()["strategy_params"] == {"deviation_threshold": 0.02, "trade_size": 50.0}
    assert db.get(Simulator, 1).strategy_params is None


def test_switching_strategy_with_params_validates_against_new_strategy(db, client) -> None:
    db.simulator(1)

    ok = _patch(client, {"strategy_name": "stat_arb_pairs", "strategy_params": {"window": 30}})
    bad = _patch(
        client, {"strategy_name": "sma_crossover", "strategy_params": {"window": 30}}
    )

    assert ok.status_code == 200 and ok.json()["strategy_params"]["window"] == 30
    assert bad.status_code == 400
    assert db.get(Simulator, 1).strategy_name == "stat_arb_pairs"


@pytest.mark.parametrize("pct", [0, 101])
def test_max_position_pct_must_be_a_real_percentage(db, client, pct) -> None:
    db.simulator(1)

    assert _patch(client, {"max_position_pct": pct}).status_code == 422
