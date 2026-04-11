from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from decimal import Decimal
from pydantic import BaseModel
from sqlalchemy import case, or_
import logging

from src.core.database import get_db
from src.core.security import get_current_active_user
from src.services.stock_data import getQuotes
from src.models.stocks import Stocks
from src.models.watchlist import Watchlist
from src.models.users import Users

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


class StockCreate(BaseModel):
    company_name: str
    ticker: str


class StockResponse(BaseModel):
    stock_id: int
    company_name: str
    ticker: str


class StockSearchItem(BaseModel):
    label: str
    value: str

    class Config:
        from_attributes = True


class StockExistsResponse(BaseModel):
    exists: bool


class WatchlistQuoteItem(BaseModel):
    watchlist_id: int
    stock_id: int
    user_id: int
    ticker: str
    company_name: str
    stockPrice: Optional[Decimal] = None
    priceChange: Optional[Decimal] = None
    priceChangePercent: Optional[Decimal] = None
    error: Optional[str] = None


@router.get("/", response_model=List[StockResponse])
def get_stocks(db: Session = Depends(get_db)):
    stocks = db.query(Stocks).all()
    return stocks


@router.get("/{stock_id}", response_model=StockResponse)
def get_stock(stock_id: int, db: Session = Depends(get_db)):
    stock = db.query(Stocks).filter(Stocks.stock_id == stock_id).first()
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")
    return stock


@router.post("/", response_model=StockResponse)
def create_stock(stock: StockCreate, db: Session = Depends(get_db)):
    db_stock = Stocks(**stock.dict())
    db.add(db_stock)
    db.commit()
    db.refresh(db_stock)
    return db_stock


@router.get("/ticker/{ticker}", response_model=StockResponse)
def get_stock_by_ticker(ticker: str, db: Session = Depends(get_db)):
    """
    Returns the stock information for a single stock given its ticker

    Args:
        ticker (str): the stock ticker

        Returns:
            general information about the stock, company, etc. stored in the database (no time-varying info such as price)
    """
    logger.info("GET /api/stocks/ticker/%s", ticker)
    try:
        safe_ticker = ticker.replace("%", r"\%").replace("_", r"\_")
        stock = db.query(Stocks).filter(Stocks.ticker.ilike(f"%{safe_ticker}%")).first()  # case insensitive comparison
    except Exception as exc:
        logger.exception("DB error looking up ticker %s: %s", ticker, exc)
        raise HTTPException(status_code=500, detail=f"Database error while looking up ticker '{ticker}': {exc}")
    if not stock:
        logger.warning("Ticker '%s' not found in database", ticker)
        raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not found in the database. Make sure it has been seeded.")
    logger.info("Found ticker %s -> stock_id=%s", ticker, stock.stock_id)
    return stock


@router.get("/exists/{ticker}", response_model=StockExistsResponse)
def stock_exists(ticker: str, db: Session = Depends(get_db)):
    exists = (
        db.query(Stocks.stock_id)
        .filter(Stocks.ticker.ilike(ticker))
        .first()
        is not None
    )
    return {"exists": exists}


@router.get("/watchlist/quotes", response_model=List[WatchlistQuoteItem])
def get_watchlist_quotes(
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_active_user),
):
    """Get the current user's watchlist enriched with ticker and live quote data."""
    logger.info("GET /api/stocks/watchlist/quotes for user_id=%s", current_user.user_id)
    try:
        rows = (
            db.query(Watchlist, Stocks)
            .join(Stocks, Stocks.stock_id == Watchlist.stock_id)
            .filter(Watchlist.user_id == current_user.user_id)
            .all()
        )
    except Exception as exc:
        logger.exception("DB error fetching watchlist for user_id=%s: %s", current_user.user_id, exc)
        raise HTTPException(status_code=500, detail=f"Database error fetching watchlist: {exc}")

    if not rows:
        return []

    tickers = [stock.ticker.upper() for _, stock in rows]
    logger.info("Fetching quotes for tickers: %s", tickers)
    try:
        price_map = getQuotes(tickers)
    except Exception as exc:
        logger.exception("getQuotes failed for tickers %s: %s", tickers, exc)
        raise HTTPException(status_code=502, detail=f"Failed to fetch live quotes for {tickers}: {exc}")

    results: List[WatchlistQuoteItem] = []
    for watch_item, stock in rows:
        ticker = stock.ticker.upper()
        price_data = price_map.get(ticker, {})
        error = price_data.get("error") if isinstance(price_data, dict) else None
        if error:
            logger.warning("Quote error for ticker %s: %s", ticker, error)

        results.append(
            WatchlistQuoteItem(
                watchlist_id=watch_item.watchlist_id,
                stock_id=watch_item.stock_id,
                user_id=watch_item.user_id,
                ticker=ticker,
                company_name=stock.company_name,
                stockPrice=None if error else price_data.get("stockPrice"),
                priceChange=None if error else price_data.get("priceChange"),
                priceChangePercent=None if error else price_data.get("priceChangePercent"),
                error=error,
            )
        )

    return results


# SEARCH FUNCTIONS --------------------------------------------------------------------------------------

@router.get("/search/{filter_string}", response_model=List[StockSearchItem])
def search_stocks(filter_string: str, db: Session = Depends(get_db)):
    """
    Search for stocks where company_name contains the filter string OR ticker starts with the filter string.

    Args:
        filter_string (str): The search term to filter by
        db (Session): Database session

    Returns:
        List[StockResponse]: List of matching stocks
    """
    LIMIT = 200  # Max number if items returned
    safe_filter = filter_string.replace("%", r"\%").replace("_", r"\_")
    stocks = db.query(Stocks).filter(
        or_(
            Stocks.ticker.ilike(f"%{safe_filter}%"),
            Stocks.company_name.ilike(f"%{safe_filter}%")
        )
    ).order_by(
        # Prioritize ticker matches over company name matches
        case(
            (Stocks.ticker == safe_filter.lower(), 0),
            (Stocks.ticker.ilike(f"{safe_filter}%"), 1),
            (Stocks.company_name.ilike(f"%{safe_filter}%"), 2),
            else_=3
        )
    ).limit(LIMIT).all()  # case insensitive comparison

    if not stocks:
        return []
    return [
        {"label": f"{stock.ticker} - {stock.company_name}", "value": stock.ticker}
        for stock in stocks
    ]
