from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.core.database import get_db
from src.main import app
from src.models.stocks import Stocks


@pytest.fixture
def client(db):
    def _get_db():
        with db.session() as session:
            yield session

    db.add(*[
        Stocks(ticker=t, company_name=name, exchange="NYSE", asset_type="Stock")
        for t, name in [
            ("AFL", "Aflac Inc"),          # contains "F", inserted before "F"
            ("F", "Ford Motor Co"),
            ("BRK-B", "Berkshire Hathaway Inc"),
            ("FDX", "FedEx Corp"),
        ]
    ])
    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_ticker_lookup_is_exact_not_substring(client) -> None:
    response = client.get("/api/stocks/ticker/F")
    assert response.json()["company_name"] == "Ford Motor Co"


@pytest.mark.parametrize("ticker", ["f", " F ", "brk.b", "BRK-B"])
def test_ticker_lookup_normalizes_case_and_dots(client, ticker: str) -> None:
    assert client.get(f"/api/stocks/ticker/{ticker}").status_code == 200


def test_unknown_ticker_is_404(client) -> None:
    assert client.get("/api/stocks/ticker/FO").status_code == 404


@pytest.mark.parametrize(("ticker", "exists"), [("F", True), ("%", False), ("_", False), ("FD", False)])
def test_exists_is_exact_and_ignores_wildcards(client, ticker: str, exists: bool) -> None:
    assert client.get(f"/api/stocks/exists/{ticker}").json() == {"exists": exists}


def test_search_ranks_exact_ticker_first(client) -> None:
    results = client.get("/api/stocks/search/f").json()
    assert results[0]["value"] == "F"
