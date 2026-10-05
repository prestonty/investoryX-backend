from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import src.routes.auth as auth_routes
from src.core.database import get_db
from src.core.security import get_password_hash
from src.main import app
from src.models.users import Users

PASSWORD = "correct-password1"


@pytest.fixture
def client(db):
    def _get_db():
        with db.session() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_register(client, monkeypatch) -> None:
    monkeypatch.setattr(auth_routes, "sendSignUpEmail", lambda *args: None)

    response = client.post(
        "/api/auth/register", json={"Name": "n", "email": "n@example.com", "password": "abcdefg1"}
    )

    assert response.status_code == 200


def test_login_refresh_logout(client, db) -> None:
    db.add(Users(user_id=1, name="u", email="u@example.com",
                 password=get_password_hash(PASSWORD), is_active=True))

    login = client.post("/api/auth/token", data={"username": "u@example.com", "password": PASSWORD})
    assert login.status_code == 200
    assert client.get("/api/auth/me").status_code == 200  # httpOnly cookie authenticates

    first_refresh = client.cookies.get("refresh_token")
    assert client.post("/api/auth/refresh").status_code == 200
    assert client.cookies.get("refresh_token") != first_refresh

    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def _request_reset_link(client, monkeypatch, email: str) -> list[str]:
    sent: list[str] = []
    monkeypatch.setattr(
        auth_routes, "sendPasswordResetEmail", lambda _email, _name, url, *_args: sent.append(url)
    )
    response = client.post("/api/auth/forgot-password", json={"email": email})
    assert response.status_code == 200
    return sent


def test_password_reset(client, db, monkeypatch) -> None:
    db.add(Users(user_id=1, name="u", email="u@example.com",
                 password=get_password_hash(PASSWORD), is_active=True))
    assert client.post(
        "/api/auth/token", data={"username": "u@example.com", "password": PASSWORD}
    ).status_code == 200

    sent = _request_reset_link(client, monkeypatch, "u@example.com")
    assert len(sent) == 1
    token = sent[0].split("token=", 1)[1]

    # The new password must meet the signup policy.
    weak = client.post("/api/auth/reset-password", json={"token": token, "password": "short"})
    assert weak.status_code == 422

    reset = client.post("/api/auth/reset-password", json={"token": token, "password": "new-password2"})
    assert reset.status_code == 200

    # Existing sessions are logged out, and only the new password works.
    assert client.get("/api/auth/me").status_code == 401
    assert client.post(
        "/api/auth/token", data={"username": "u@example.com", "password": PASSWORD}
    ).status_code == 401
    assert client.post(
        "/api/auth/token", data={"username": "u@example.com", "password": "new-password2"}
    ).status_code == 200

    # The link only works once.
    reuse = client.post("/api/auth/reset-password", json={"token": token, "password": "another-pass3"})
    assert reuse.status_code == 400


def test_forgot_password_unknown_email(client, monkeypatch) -> None:
    sent = _request_reset_link(client, monkeypatch, "nobody@example.com")
    assert sent == []


def test_reset_password_rejects_other_token_types(client, db) -> None:
    from src.core.security import create_email_verification_token

    db.add(Users(user_id=1, name="u", email="u@example.com",
                 password=get_password_hash(PASSWORD), is_active=True))
    token = create_email_verification_token(1)
    response = client.post("/api/auth/reset-password", json={"token": token, "password": "new-password2"})
    assert response.status_code == 400
