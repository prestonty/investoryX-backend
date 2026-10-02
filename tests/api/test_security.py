from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

import src.core.security as security
import src.routes.dev as dev_routes
import src.routes.market_data as market_data_routes
from src.core.config import settings
from src.core.database import get_db
from src.core.security import (
    create_access_token,
    create_email_verification_token,
    create_refresh_token,
    get_password_hash,
)
from src.main import app
from src.models.users import Users


@pytest.fixture
def client(db):
    def _get_db():
        with db.session() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def user(db) -> Users:
    db.add(Users(user_id=1, name="u", email="u@example.com",
                 password=get_password_hash("correct-password"), is_active=True))
    return db.get(Users, 1)


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _legacy_token(claims: dict, key: str = security.SECRET_KEY) -> str:
    """A token as issued before the "type" claim existed."""
    from datetime import datetime
    payload = {**claims, "exp": datetime.utcnow() + timedelta(minutes=5)}
    return security.jwt.encode(payload, key, algorithm=security.ALGORITHM)


# --- token types -------------------------------------------------------------

def test_access_token_authenticates(client, db, user) -> None:
    response = client.get("/api/auth/me", headers=_bearer(db.access_token(1)))
    assert response.status_code == 200


def test_email_verification_token_is_not_a_login(client, user) -> None:
    token = create_email_verification_token(1)
    assert client.get("/api/auth/me", headers=_bearer(token)).status_code == 401


def test_refresh_token_is_not_an_access_token(client, user) -> None:
    token = create_refresh_token({"sub": "1"})
    assert client.get("/api/auth/me", headers=_bearer(token)).status_code == 401


def test_legacy_untyped_access_token_is_rejected(client, user) -> None:
    # The frontend then calls /api/auth/refresh and gets a typed token.
    assert client.get("/api/auth/me", headers=_bearer(_legacy_token({"sub": "1"}))).status_code == 401


def test_refresh_accepts_legacy_untyped_refresh_cookie(client, user) -> None:
    client.cookies.set("refresh_token", _legacy_token({"sub": "1"}, security.REFRESH_SECRET_KEY))

    response = client.post("/api/auth/refresh")

    # The legacy token is converted into a session; the new tokens arrive as cookies.
    assert response.status_code == 200
    assert "access_token" not in response.json()
    assert client.get("/api/auth/me").status_code == 200


def test_refresh_rejects_access_token_cookie(client, user) -> None:
    client.cookies.set("refresh_token", create_access_token({"sub": "1"}))
    assert client.post("/api/auth/refresh").status_code == 401


def test_email_verification_link_still_activates(client, db) -> None:
    db.add(Users(user_id=2, name="n", email="n@example.com", password="x", is_active=False))

    response = client.get("/api/auth/verify-email", params={"token": create_email_verification_token(2)})

    assert response.json() == {"message": "Email verified successfully"}
    assert db.get(Users, 2).is_active is True


def test_login_checks_a_password_hash_even_for_unknown_emails(client, monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(security, "verify_password", lambda plain, hashed: calls.append(hashed) or False)

    response = client.post("/api/auth/token", data={"username": "nobody@example.com", "password": "x"})

    assert response.status_code == 401
    assert calls == [security._DUMMY_PASSWORD_HASH]


# --- removed endpoints -------------------------------------------------------

@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/users/"),             # created pre-verified users without auth
        ("post", "/send-sign-up-email"),     # open email relay
        ("post", "/send-welcome-email"),     # open email relay
        ("post", "/api/auth/test-email"),    # open email relay
        ("post", "/api/stocks/"),            # unauthenticated writes to the shared catalog
    ],
)
def test_removed_endpoints_are_gone(client, method: str, path: str) -> None:
    assert getattr(client, method)(path, json={}).status_code in (404, 405)


# --- dev pipeline ------------------------------------------------------------

@pytest.fixture
def pipeline_calls(monkeypatch) -> list:
    calls: list = []
    monkeypatch.setattr(dev_routes, "run_pipeline", lambda day: calls.append(day) or {"day": str(day)})
    monkeypatch.setattr(settings, "dev_mode", True)
    return calls


def test_dev_pipeline_is_not_a_get(client, pipeline_calls) -> None:
    assert client.get("/dev/run-pipeline").status_code == 405
    assert pipeline_calls == []


def test_dev_pipeline_requires_login(client, pipeline_calls) -> None:
    assert client.post("/dev/run-pipeline").status_code == 401
    assert pipeline_calls == []


def test_dev_pipeline_requires_dev_mode(client, db, user, pipeline_calls, monkeypatch) -> None:
    monkeypatch.setattr(settings, "dev_mode", False)
    response = client.post("/dev/run-pipeline", headers=_bearer(db.access_token(1)))
    assert response.status_code == 403
    assert pipeline_calls == []


def test_dev_pipeline_refuses_old_days(client, db, user, pipeline_calls) -> None:
    response = client.post(
        "/dev/run-pipeline",
        params={"day": "2025-01-02"},
        headers=_bearer(db.access_token(1)),
    )
    assert response.status_code == 400
    assert pipeline_calls == []


def test_dev_pipeline_runs_for_logged_in_user(client, db, user, pipeline_calls) -> None:
    response = client.post("/dev/run-pipeline", headers=_bearer(db.access_token(1)))
    assert response.status_code == 200
    assert pipeline_calls == [None]


# --- data isolation and error leaks ------------------------------------------

def test_backtest_status_requires_task_to_belong_to_simulator(client, db, user, monkeypatch) -> None:
    db.simulator(5, user_id=1)

    class _OtherUsersResult:
        def __init__(self, task_id):
            self.state = "SUCCESS"
            self.result = {"simulator_id": 99, "pnl": "123"}

    monkeypatch.setattr("src.celery_app.app.AsyncResult", _OtherUsersResult)

    response = client.get(
        "/api/simulator/5/backtest/status/some-task",
        headers=_bearer(db.access_token(1)),
    )

    assert response.status_code == 404


def test_market_data_errors_do_not_leak_details(client, monkeypatch) -> None:
    def _boom(*_args):
        raise RuntimeError("connect to internal-host:5432 failed, password=hunter2")

    monkeypatch.setattr(market_data_routes, "getTopGainers", _boom)

    response = client.get("/top-gainers")

    assert response.status_code == 502
    assert "hunter2" not in response.text and "internal-host" not in response.text
