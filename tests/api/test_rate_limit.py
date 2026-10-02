from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

import src.core.rate_limit as rate_limit
import src.core.redis_client as redis_client
from src.core.config import settings
from src.core.database import get_db
from src.main import app


@pytest.fixture
def limited(monkeypatch):
    """Rate limiting on, counting in memory (as when Redis is down)."""
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(rate_limit, "get_redis", lambda: None)
    # Freeze the clock mid-window so a test can't straddle a window boundary.
    monkeypatch.setattr(rate_limit, "_now", lambda: 1_000_030.0)
    rate_limit._memory_counts.clear()
    yield
    rate_limit._memory_counts.clear()


@pytest.fixture
def client(db):
    def _get_db():
        with db.session() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_login_is_limited_per_ip(client, limited) -> None:
    form = {"username": "nobody@example.com", "password": "wrong"}

    statuses = [client.post("/api/auth/token", data=form).status_code for _ in range(11)]

    assert statuses[:10] == [401] * 10
    assert statuses[10] == 429
    assert int(client.post("/api/auth/token", data=form).headers["Retry-After"]) > 0


def test_limits_are_per_route(client, limited) -> None:
    form = {"username": "nobody@example.com", "password": "wrong"}
    for _ in range(11):
        client.post("/api/auth/token", data=form)

    # Exhausting the login limit doesn't block other endpoints.
    assert client.get("/dev/flags").status_code == 200
    assert client.post("/api/auth/refresh").status_code == 401


def test_disabled_limits_never_block(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    form = {"username": "nobody@example.com", "password": "wrong"}
    assert {client.post("/api/auth/token", data=form).status_code for _ in range(15)} == {401}


def test_counts_in_redis_when_available(monkeypatch) -> None:
    store: dict[str, int] = {}

    class _Pipeline:
        def __init__(self):
            self.ops = []

        def incr(self, key):
            self.ops.append(key)

        def expire(self, key, seconds):
            pass

        def execute(self):
            key = self.ops[0]
            store[key] = store.get(key, 0) + 1
            return [store[key], True]

    class _FakeRedis:
        def pipeline(self):
            return _Pipeline()

    monkeypatch.setattr(rate_limit, "get_redis", lambda: _FakeRedis())
    limiter = rate_limit.RateLimit("t", limit=2, window_seconds=60)

    assert [limiter._hit("k") for _ in range(3)] == [1, 2, 3]
    assert store == {"k": 3}


def _request(peer: str, forwarded: str | None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1234)})


def test_forwarded_header_ignored_unless_trusted(monkeypatch) -> None:
    monkeypatch.setattr(settings, "trust_proxy_headers", False)
    assert rate_limit.client_ip(_request("10.0.0.1", "1.2.3.4")) == "10.0.0.1"


def test_trusted_proxy_uses_address_it_appended(monkeypatch) -> None:
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    # The client can forge the first entry; the proxy appends the real address last.
    assert rate_limit.client_ip(_request("10.0.0.1", "6.6.6.6, 203.0.113.9")) == "203.0.113.9"


def test_unreachable_redis_is_not_retried_on_every_call(monkeypatch) -> None:
    attempts: list[str] = []

    def _unreachable(url, **kwargs):
        attempts.append(url)
        assert kwargs["socket_connect_timeout"] <= 1
        raise ConnectionError("down")

    monkeypatch.setattr(redis_client.redis, "from_url", _unreachable)
    monkeypatch.setattr(redis_client, "_client", None)
    monkeypatch.setattr(redis_client, "_unavailable_until", 0.0)

    assert redis_client.get_redis() is None
    assert redis_client.get_redis() is None
    assert len(attempts) == 1
