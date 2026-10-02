from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import src.routes.auth as auth_routes
from src.core.database import get_db
from src.core.security import get_password_hash
from src.main import app
from src.models.user_session import UserSession
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


@pytest.fixture
def user(db) -> None:
    db.add(Users(user_id=1, name="u", email="u@example.com",
                 password=get_password_hash(PASSWORD), is_active=True))


def _login(client: TestClient):
    response = client.post("/api/auth/token", data={"username": "u@example.com", "password": PASSWORD})
    assert response.status_code == 200
    return response


def _set_cookie_headers(response) -> list[str]:
    return response.headers.get_list("set-cookie")


def test_login_sets_httponly_cookies_and_cookie_auth_works(client, user) -> None:
    response = _login(client)

    cookies = {h.split("=", 1)[0]: h for h in _set_cookie_headers(response)}
    assert "HttpOnly" in cookies["access_token"]
    assert "HttpOnly" in cookies["refresh_token"] and "Path=/api/auth" in cookies["refresh_token"]
    assert "HttpOnly" not in cookies["session_active"]  # UI hint only, holds no secret
    # No Authorization header: the httpOnly cookie alone authenticates.
    assert client.get("/api/auth/me").status_code == 200


def test_logout_revokes_tokens_immediately(client, user) -> None:
    access_token = _login(client).json()["access_token"]
    old_refresh = client.cookies.get("refresh_token")

    assert client.post("/api/auth/logout").status_code == 200

    # The access token hasn't expired, but its session is revoked.
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {access_token}"}).status_code == 401
    client.cookies.set("refresh_token", old_refresh, path="/api/auth")
    assert client.post("/api/auth/refresh").status_code == 401


def test_refresh_rotates_the_refresh_token(client, user) -> None:
    _login(client)
    first_refresh = client.cookies.get("refresh_token")

    response = client.post("/api/auth/refresh")

    assert response.status_code == 200
    assert "access_token" not in response.json()  # tokens only ever travel as cookies
    assert client.cookies.get("refresh_token") != first_refresh
    assert client.get("/api/auth/me").status_code == 200


def test_reusing_an_old_refresh_token_revokes_the_session(client, db, user) -> None:
    _login(client)
    stolen = client.cookies.get("refresh_token")
    client.post("/api/auth/refresh")  # legitimate rotation; `stolen` is now stale
    [session] = db.all(UserSession)
    with db.session() as s:  # move the rotation outside the concurrent-refresh grace window
        row = s.get(UserSession, session.session_id)
        row.rotated_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        s.commit()

    attacker = TestClient(app)
    attacker.cookies.set("refresh_token", stolen, path="/api/auth")
    assert attacker.post("/api/auth/refresh").status_code == 401

    # The whole session is revoked, so the legitimate user is logged out too.
    assert db.get(UserSession, session.session_id).revoked_reason == "refresh_token_reuse"
    assert client.get("/api/auth/me").status_code == 401


def test_concurrent_refresh_from_two_tabs_is_not_treated_as_theft(client, db, user) -> None:
    _login(client)
    shared = client.cookies.get("refresh_token")
    client.post("/api/auth/refresh")  # tab 1 rotates

    other_tab = TestClient(app)
    other_tab.cookies.set("refresh_token", shared, path="/api/auth")
    assert other_tab.post("/api/auth/refresh").status_code == 200  # tab 2, moments later

    [session] = db.all(UserSession)
    assert session.revoked_at is None


def test_failed_refresh_clears_auth_cookies(client) -> None:
    client.cookies.set("refresh_token", "garbage", path="/api/auth")

    response = client.post("/api/auth/refresh")

    assert response.status_code == 401
    cleared = " ".join(_set_cookie_headers(response))
    assert "session_active=" in cleared and "access_token=" in cleared


# --- password policy ---------------------------------------------------------

@pytest.mark.parametrize(
    ("password", "message"),
    [
        ("short1", "at least 8 characters"),
        ("onlyletters", "at least one number"),
        ("12345678", "at least one letter"),
    ],
)
def test_register_rejects_weak_passwords(client, password: str, message: str) -> None:
    response = client.post(
        "/api/auth/register", json={"Name": "n", "email": "n@example.com", "password": password}
    )
    assert response.status_code == 422
    assert message in response.text


def test_register_accepts_policy_compliant_password(client, monkeypatch) -> None:
    monkeypatch.setattr(auth_routes, "sendSignUpEmail", lambda *args: None)
    response = client.post(
        "/api/auth/register", json={"Name": "n", "email": "n@example.com", "password": "abcdefg1"}
    )
    assert response.status_code == 200
