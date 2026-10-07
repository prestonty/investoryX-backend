from __future__ import annotations

import pytest

import src.services.listings_sync as listings_sync
from src.models.stocks import Stocks
from src.services.listings_sync import ListingsFetchError, sync_listings
from src.trading_engine.tasks.sync_listings import sync_listings_task

HEADER = "symbol,name,exchange,assetType,ipoDate,delistingDate,status"


def _listing_csv(*extra_rows: str, filler: int = listings_sync.MIN_EXPECTED_ROWS) -> str:
    rows = [f"T{i},Company {i},NYSE,Stock,2000-01-01,null,Active" for i in range(filler)]
    return "\n".join([HEADER, *rows, *extra_rows]) + "\n"


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        pass


@pytest.fixture
def alpha_vantage(monkeypatch: pytest.MonkeyPatch):
    """Serve the given text as Alpha Vantage's response."""

    def serve(text: str) -> None:
        monkeypatch.setattr(
            listings_sync.requests, "get", lambda *a, **kw: _FakeResponse(text)
        )

    return serve


def test_adds_only_new_tickers_and_keeps_existing_ids(db, alpha_vantage):
    db.add(Stocks(stock_id=500, company_name="Old Name", ticker="T0", exchange="NYSE", asset_type="Stock"))
    alpha_vantage(_listing_csv("SPCX,SpaceX,NASDAQ,Stock,2026-10-01,null,Active"))

    with db.session() as session:
        added = sync_listings(session)
        session.commit()

    assert "SPCX" in added
    assert "T0" not in added
    existing = db.all(Stocks, ticker="T0")
    assert [(s.stock_id, s.company_name) for s in existing] == [(500, "Old Name")]
    assert len(db.all(Stocks, ticker="SPCX")) == 1


def test_skips_incomplete_and_duplicate_rows(db, alpha_vantage):
    alpha_vantage(
        _listing_csv(
            "NONAME,,NYSE,Stock,2026-10-01,null,Active",
            "DUP,First,NYSE,Stock,2026-10-01,null,Active",
            "DUP,Second,NYSE,Stock,2026-10-01,null,Active",
        )
    )

    with db.session() as session:
        added = sync_listings(session)
        session.commit()

    assert "NONAME" not in added
    assert [s.company_name for s in db.all(Stocks, ticker="DUP")] == ["First"]


def test_second_run_adds_nothing(db, alpha_vantage):
    alpha_vantage(_listing_csv())

    with db.session() as session:
        sync_listings(session)
        session.commit()
    with db.session() as session:
        assert sync_listings(session) == []


@pytest.mark.parametrize(
    "body",
    [
        '{"Information": "API rate limit reached"}',
        _listing_csv(filler=5),
    ],
    ids=["rate-limit-json", "truncated-csv"],
)
def test_bad_response_inserts_nothing(db, alpha_vantage, body):
    alpha_vantage(body)

    with db.session() as session:
        with pytest.raises(ListingsFetchError):
            sync_listings(session)

    assert db.all(Stocks) == []


def test_task_commits_and_returns_count(db, alpha_vantage):
    alpha_vantage(_listing_csv("SPCX,SpaceX,NASDAQ,Stock,2026-10-01,null,Active"))

    assert sync_listings_task() == listings_sync.MIN_EXPECTED_ROWS + 1
    assert len(db.all(Stocks, ticker="SPCX")) == 1
