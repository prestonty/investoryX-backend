import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from src.api.services.stock_data_service import (
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


router = APIRouter(tags=["market-data"])

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
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stock-overview/{ticker}")
def get_stock_overview(ticker: str):
    """
    Get advanced information about a stock from its ticker symbol.
    """
    try:
        return getStockOverview(ticker)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stock-news")
def get_stock_news(max_articles: int = Query(default=20, description="Max number of articles")):
    try:
        return getStockNews(max_articles)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/major-etfs")
def get_major_etfs():
    # We can get away with reusing the getStockPrice function again
    pass


@router.get("/stock-history/{ticker}")
def get_stock_history(ticker: str, period: Period, interval: Interval):
    try:
        return getStockHistory(ticker, period, interval)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get-default-indexes")
def get_default_indexes():
    """
    Get a list of default market index etfs to display on the homepage.
    """
    try:
        with ETF_PATH.open("r", encoding="utf-8") as f:
            default_etfs = json.load(f)
    except FileNotFoundError:
        raise HTTPException(404, detail=f"Default ETF file not found at {ETF_PATH}")
    except json.JSONDecodeError as e:
        raise HTTPException(500, detail=f"Invalid JSON in {ETF_PATH}: {e}")

    try:
        return getDefaultIndexes(default_etfs)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/top-gainers")
def get_top_gainers(limit: int = Query(default=5, description="Number of top gainers to return")):
    """
    Get top gainers (stocks with highest percentage gains).
    """
    try:
        return getTopGainers(limit)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/top-losers")
def get_top_losers(limit: int = Query(default=5, description="Number of top losers to return")):
    """
    Get top losers (stocks with highest percentage losses).
    """
    try:
        return getTopLosers(limit)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/most-active")
def get_most_active(limit: int = Query(default=5, description="Number of most active stocks to return")):
    """
    Get most actively traded stocks (highest volume).
    """
    try:
        return getMostActive(limit)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
