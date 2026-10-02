import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from src.core.rate_limit import RateLimit

from src.services.stock_data import (
    getDefaultIndexes,
    getMostActive,
    getStockHistory,
    getStockNews,
    getStockOverview,
    getStockPrice,
    getTopGainers,
    getTopLosers,
)
from src.data_types.history import Period, Interval


logger = logging.getLogger("investoryx.market_data")

# Each request hits Yahoo or scrapes stockanalysis.com; cap per-IP volume so
# one client can't get the server's IP rate-limited or blocked upstream.
router = APIRouter(
    tags=["market-data"],
    dependencies=[Depends(RateLimit("market_data", limit=120, window_seconds=60))],
)


def _upstream_error(exc: Exception) -> HTTPException:
    # Log the provider error; don't echo upstream/internal details to clients.
    logger.error("Market data request failed: %s", exc)
    return HTTPException(status_code=502, detail="Market data is temporarily unavailable")

NAME = "market_index_ETFs_2.json"
ETF_PATH = Path(__file__).resolve().parents[2] / "data" / "stocklist" / NAME


@router.get("/stocks/{ticker}")
def get_stock_price(ticker: str):
    """
    Get basic information about a stock - company name, price, price change from its ticker symbol.
    """
    try:
        return getStockPrice(ticker)
    except RuntimeError as e:
        raise _upstream_error(e)


@router.get("/stock-overview/{ticker}")
def get_stock_overview(ticker: str):
    """
    Get advanced information about a stock from its ticker symbol.
    """
    try:
        return getStockOverview(ticker)
    except RuntimeError as e:
        raise _upstream_error(e)


@router.get("/stock-news")
def get_stock_news(max_articles: int = Query(default=20, description="Max number of articles")):
    try:
        return getStockNews(max_articles)
    except RuntimeError as e:
        raise _upstream_error(e)


@router.get("/major-etfs")
def get_major_etfs():
    # We can get away with reusing the getStockPrice function again
    pass


@router.get("/stock-history/{ticker}")
def get_stock_history(ticker: str, period: Period, interval: Interval):
    try:
        return getStockHistory(ticker, period, interval)
    except RuntimeError as e:
        raise _upstream_error(e)


@router.get("/get-default-indexes")
def get_default_indexes():
    """
    Get a list of default market index etfs to display on the homepage.
    """
    try:
        with ETF_PATH.open("r", encoding="utf-8") as f:
            default_etfs = json.load(f)
    except FileNotFoundError:
        logger.exception("Default ETF file not found at %s", ETF_PATH)
        raise HTTPException(500, detail="Default indexes are unavailable")
    except json.JSONDecodeError as e:
        logger.exception("Invalid JSON in %s", ETF_PATH)
        raise HTTPException(500, detail="Default indexes are unavailable")

    try:
        return getDefaultIndexes(default_etfs)
    except RuntimeError as e:
        raise _upstream_error(e)


@router.get("/top-gainers")
def get_top_gainers(
    limit: int = Query(default=5, description="Number of top gainers to return"),
    min_price: float = Query(default=4.0, description="Minimum stock price to exclude penny stocks"),
):
    """
    Get top gainers (stocks with highest percentage gains).
    """
    try:
        return getTopGainers(limit, min_price)
    except RuntimeError as e:
        raise _upstream_error(e)


@router.get("/top-losers")
def get_top_losers(
    limit: int = Query(default=5, description="Number of top losers to return"),
    min_price: float = Query(default=4.0, description="Minimum stock price to exclude penny stocks"),
):
    """
    Get top losers (stocks with highest percentage losses).
    """
    try:
        return getTopLosers(limit, min_price)
    except RuntimeError as e:
        raise _upstream_error(e)


@router.get("/most-active")
def get_most_active(
    limit: int = Query(default=5, description="Number of most active stocks to return"),
    min_price: float = Query(default=4.0, description="Minimum stock price to exclude penny stocks"),
):
    """
    Get most actively traded stocks (highest volume).
    """
    try:
        return getMostActive(limit, min_price)
    except RuntimeError as e:
        raise _upstream_error(e)
