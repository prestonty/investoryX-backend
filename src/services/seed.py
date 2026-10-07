import logging
import sys

import requests

from src.core.database import SessionLocal
from src.models.stocks import Stocks
from src.services.listings_sync import ListingsFetchError, sync_listings

logger = logging.getLogger("investoryx.seed")


def stocks_table_is_empty():
    """Check whether the stocks table has any rows"""
    db = SessionLocal()
    try:
        return db.query(Stocks).first() is None
    finally:
        db.close()


def main():
    logging.basicConfig(level=logging.INFO)

    # --if-empty lets docker compose run the seed on every startup without
    # re-downloading. Later listings come from the daily stocks.sync_listings task.
    if "--if-empty" in sys.argv and not stocks_table_is_empty():
        logger.info("Stocks table already populated, skipping seed")
        return

    logger.info("Downloading stock listings from Alpha Vantage...")
    db = SessionLocal()
    try:
        added = sync_listings(db)
        db.commit()
        logger.info("Inserted %d stocks", len(added))
    except (requests.RequestException, ListingsFetchError) as e:
        # Don't fail startup (the backend waits on this step); the daily sync retries.
        db.rollback()
        logger.error("Failed to seed stocks: %s", e)
    finally:
        db.close()


if __name__ == "__main__":
    main()
