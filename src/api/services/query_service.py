from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List
from src.models.stocks import Stocks

def query_search(filter_string: str, db: Session) -> List[Stocks]:
    """
    Search for stocks where company_name contains the filter string OR ticker starts with the filter string.
    
    Args:
        filter_string (str): The search term to filter by
        db (Session): Database session
    
    Returns:
        List[Stocks]: List of matching stocks
    """
    try:
        # Case-insensitive search
        # company_name contains filter_string OR ticker starts with filter_string
        stocks = db.query(Stocks).filter(
            or_(
                Stocks.company_name.ilike(f"%{filter_string}%"),
                Stocks.ticker.ilike(f"{filter_string}%")
            )
        ).all()
        
        return stocks
        
    except Exception as e:
        # Log the error (you might want to add proper logging here)
        print(f"Error in query_search: {e}")
        return []

def query_search_by_company_name(company_name: str, db: Session) -> List[Stocks]:
    """
    Search for stocks by company name (contains).
    
    Args:
        company_name (str): Company name to search for
        db (Session): Database session
    
    Returns:
        List[Stocks]: List of matching stocks
    """
    try:
        stocks = db.query(Stocks).filter(
            Stocks.company_name.ilike(f"%{company_name}%")
        ).all()
        
        return stocks
        
    except Exception as e:
        print(f"Error in query_search_by_company_name: {e}")
        return []

def query_search_by_ticker(ticker: str, db: Session) -> List[Stocks]:
    """
    Search for stocks by ticker (starts with).
    
    Args:
        ticker (str): Ticker to search for
        db (Session): Database session
    
    Returns:
        List[Stocks]: List of matching stocks
    """
    try:
        stocks = db.query(Stocks).filter(
            Stocks.ticker.ilike(f"{ticker}%")
        ).all()
    
    return stocks
    
    except Exception as e:
        print(f"Error in query_search_by_ticker: {e}")
        return []


