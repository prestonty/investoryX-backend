from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
from sqlalchemy import case, or_

from src.api.database.database import get_db
from src.models.stocks import Stocks

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
    stock = db.query(Stocks).filter(Stocks.ticker.ilike(f"%{ticker}%")).first() # case insensitive comparison
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")
    return stock

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
    LIMIT = 200 # Max number if items returned
    stocks = db.query(Stocks).filter(
        or_(
            Stocks.ticker.ilike(f"%{filter_string}%"),
            Stocks.company_name.ilike(f"%{filter_string}%")
        )
    ).order_by(
        # Prioritize ticker matches over company name matches
        case(
            (Stocks.ticker == filter_string.lower(), 0),
            (Stocks.ticker.ilike(f"{filter_string}%"), 1),
            (Stocks.company_name.ilike(f"{filter_string}%"), 2),
            else_=3
        )
    ).limit(LIMIT).all() # case insensitive comparison
    
    if not stocks:
        raise HTTPException(status_code=404, detail="Stock not found")
    return [
    {"label": f"{stock.ticker} - {stock.company_name}", "value": stock.ticker}
    for stock in stocks
]