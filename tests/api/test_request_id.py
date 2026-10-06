from __future__ import annotations

from fastapi.testclient import TestClient

from src.core.config import settings
from src.main import app


def test_echoes_a_valid_client_request_id() -> None:
    response = TestClient(app).get("/health", headers={"X-Request-ID": "abc-123"})
    assert response.headers["X-Request-ID"] == "abc-123"


def test_generates_an_id_when_missing_or_unsafe() -> None:
    client = TestClient(app)
    generated = client.get("/health").headers["X-Request-ID"]
    assert len(generated) == 32

    # Newlines or overlong values could forge log lines, so they're replaced.
    unsafe = client.get("/health", headers={"X-Request-ID": "x" * 100})
    assert unsafe.headers["X-Request-ID"] != "x" * 100


def test_unhandled_errors_return_500_with_request_id_and_cors_headers() -> None:
    def boom():
        raise RuntimeError("kaboom")

    app.add_api_route("/__test_boom", boom)
    try:
        response = TestClient(app, raise_server_exceptions=False).get(
            "/__test_boom",
            headers={"X-Request-ID": "req-1", "Origin": settings.cors_origins[0]},
        )
    finally:
        app.router.routes.pop()

    assert response.status_code == 500
    assert response.json()["request_id"] == "req-1"
    assert response.headers["X-Request-ID"] == "req-1"
    # Without CORS headers the browser can't read the error at all.
    assert response.headers.get("access-control-allow-origin") == settings.cors_origins[0]
