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
            ("FDX", "FedEx Corp"),
        ]
    ])
    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_ticker_lookup(client) -> None:
    response = client.get("/api/stocks/ticker/F")
    assert response.json()["company_name"] == "Ford Motor Co"


def test_search_ranks_exact_ticker_first(client) -> None:
    results = client.get("/api/stocks/search/f").json()
    assert results[0]["value"] == "F"
