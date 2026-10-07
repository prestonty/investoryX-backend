import logging

from celery import shared_task

from src.core.database import SessionLocal
from src.services.listings_sync import sync_listings

logger = logging.getLogger("investoryx.listings_sync")


@shared_task(name="stocks.sync_listings")
def sync_listings_task() -> int:
    """
    Add newly listed tickers (e.g. IPOs) to the stocks table.

    Safe to run any time: existing rows are left alone, so a missed run is
    simply caught up by the next one.
    """
    db = SessionLocal()
    try:
        added = sync_listings(db)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("sync_listings failed")
        raise
    finally:
        db.close()

    logger.info("sync_listings: added %d tickers: %s", len(added), added)
    return len(added)
