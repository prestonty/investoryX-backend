from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel

from src.api.database.database import get_db
from src.models.stocks import Stocks
from src.api.services.query_service import query_search

router = APIRouter(prefix="/api/stocks", tags=["stocks"])

class StockCreate(BaseModel):
    company_name: str
    ticker: str

class StockResponse(BaseModel):
    stock_id: int
    company_name: str
    ticker: str

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
    stock = db.query(Stocks).filter(Stocks.ticker == ticker.upper()).first()
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")
    return stock

@router.get("/search/{filter_string}", response_model=List[StockResponse])
def search_stocks(filter_string: str, db: Session = Depends(get_db)):
    """
    Search for stocks where company_name contains the filter string OR ticker starts with the filter string.
    
    Args:
        filter_string (str): The search term to filter by
        db (Session): Database session
    
    Returns:
        List[StockResponse]: List of matching stocks
    """
    if not filter_string or len(filter_string.strip()) == 0:
        raise HTTPException(status_code=400, detail="Filter string cannot be empty")
    
    stocks = query_search(filter_string.strip(), db)
    return stocks