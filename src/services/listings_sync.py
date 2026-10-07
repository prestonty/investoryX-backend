import csv
import io
import logging
import os

import requests
from sqlalchemy.orm import Session

from src.models.stocks import Stocks

logger = logging.getLogger("investoryx.listings_sync")

LISTING_STATUS_URL = "https://www.alphavantage.co/query"
REQUIRED_FIELDS = ("symbol", "name", "exchange", "assetType")
# A full active listing is ~12k rows; far fewer means an error page or a
# truncated download, and syncing from it would miss most of the market.
MIN_EXPECTED_ROWS = 1000


class ListingsFetchError(RuntimeError):
    """Alpha Vantage returned something other than a usable listing CSV."""


def _api_key() -> str:
    key = os.getenv("ALPHAVANTAGE_API_KEY")
    if not key:
        logger.warning("ALPHAVANTAGE_API_KEY is not set; using the demo key")
        return "demo"
    return key


def parse_listings_csv(csv_content: str) -> list[dict[str, str]]:
    """
    Parse Alpha Vantage's LISTING_STATUS CSV, keeping rows with every required field.

    Alpha Vantage answers rate limits and bad keys with HTTP 200 and a JSON note
    instead of CSV, so anything that isn't the expected CSV raises.
    """
    csv_content = csv_content.lstrip("﻿")
    if not csv_content.startswith("symbol,"):
        raise ListingsFetchError(f"Unexpected listing response: {csv_content[:200]!r}")

    listings = []
    for row in csv.DictReader(io.StringIO(csv_content)):
        values = {field: (row.get(field) or "").strip() for field in REQUIRED_FIELDS}
        if all(values.values()):
            listings.append(values)

    if len(listings) < MIN_EXPECTED_ROWS:
        raise ListingsFetchError(
            f"Only {len(listings)} listings returned; "
            f"expected at least {MIN_EXPECTED_ROWS}"
        )
    return listings


def fetch_active_listings() -> list[dict[str, str]]:
    """Download every actively traded US listing from Alpha Vantage."""
    response = requests.get(
        LISTING_STATUS_URL,
        params={"function": "LISTING_STATUS", "apikey": _api_key()},
        timeout=60,
    )
    response.raise_for_status()
    return parse_listings_csv(response.text)


def sync_listings(db: Session) -> list[str]:
    """
    Add listings missing from the stocks table (e.g. new IPOs) and return their tickers.

    Existing rows are never modified, so stock_ids referenced elsewhere stay stable.
    Alpha Vantage already uses Yahoo-style tickers (BRK-B), matching ticker lookups.
    The caller commits.
    """
    listings = fetch_active_listings()
    existing = {ticker for (ticker,) in db.query(Stocks.ticker)}

    new_stocks: dict[str, Stocks] = {}
    for row in listings:
        ticker = row["symbol"]
        if ticker in existing or ticker in new_stocks:
            continue
        new_stocks[ticker] = Stocks(
            company_name=row["name"],
            ticker=ticker,
            exchange=row["exchange"],
            asset_type=row["assetType"],
        )

    db.add_all(new_stocks.values())
    return list(new_stocks)
