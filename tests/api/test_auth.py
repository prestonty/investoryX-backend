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
