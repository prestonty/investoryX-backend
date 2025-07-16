from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import json

from src.api.data_access.stock_data_provider import *
from src.api.services.query_service import *
from src.dataTypes.history import Period, Interval


# Create the tables if they do not exist - TODO: Use Alembic as a migration tool to do this in future
from src.api.database.database import engine, Base
import src.models.users
import src.models.stocks
import src.models.watchlist
from src.api.routes import stocks, users, watchlist

Base.metadata.create_all(bind=engine)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"], # TODO: Change and put this in .env later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Hello, FastAPI!"}

# DATABASE ROUTES --------------------------------------------------------------------------------------
app.include_router(stocks.router)
app.include_router(users.router)
app.include_router(watchlist.router)





# SEARCH FUNCTIONS --------------------------------------------------------------------------------------

@app.get("/search/ticker/{ticker}")
def search_ticker(ticker: str):
    """
    Search for a stock by its ticker symbol.
    
    Args:
        ticker (str): The ticker symbol to search for.
    
    Returns:
        dict: Stock information if found, else raises HTTPException.
    """
    stocks = searchStocksByTicker(ticker)
    if not stocks:
        raise HTTPException(status_code=404, detail="Stock not found")
    return stocks

@app.get("/search/company-name/{company_name}")
def search_company_name(company_name: str):
    """
    Search for a stock by its ticker symbol.
    
    Args:
        ticker (str): The ticker symbol to search for.
    
    Returns:
        dict: Stock information if found, else raises HTTPException.
    """
    stocks = searchStocksByCompanyName(company_name)
    if not stocks:
        raise HTTPException(status_code=404, detail="Stock not found")
    return stocks

@app.get("/search/stocks/{filter_string}")
def searchStocks(filter_string: str):
    """
    Search for stocks either by company name or ticker symbol.
    
    Args:
        filter_string (str): The filter string to search for.
    
    Returns:
        dict: Stock information if found, else raises HTTPException.
    """
    stocks = searchStocks(filter_string)
    if not stocks:
        raise HTTPException(status_code=404, detail="Stock not found")
    return stocks

# 1. search function via ticker symbol (E.g. appl for apple)
# this function is boolean and will check if the SQL database contains this stock symbol
# boolean return

# 2. search function via stock name (E.g. Apple Inc)
# this function maps the stock name to the ticker so we can use the "/stocks" route to fetch the data
# map the stock name to the ticker in the database
# string return (ticker symbol)

# STOCK INFO FUNCTIONS ----------------------------------------------------------------------------------

# Get stock info function - returns all the stock information from the page (heavy function)
@app.get("/stocks/{ticker}")
def get_StockPrice(ticker: str):
    """
    Get a stock's price and other details from its ticker symbol

    Args:
        ticker (str): The ticker symbol of the stock

    Returns:
        dict: Stock information if found, else raises HTTPException.
    """
    try:
        return getStockPrice(ticker)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


# Get more advanced data from stock for display page
@app.get("/stock-overview/{ticker}")
def get_StockOverview(ticker: str):
    try:
        return getStockOverview(ticker)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    
# STOCK NEWS ---------------------------------------------------------------
@app.get("/stock-news")
def get_StockNews(max_articles: int = Query(default=20, description="Max number of articles")):
    try:
        return getStockNews(max_articles)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

# Fetch market indices and it sprices (Dows Jones, NasDaq, NYSE)
@app.get("/major-etfs")
def get_MajorETFs():
    # with open("data/etfs.json", "r") as f:
    #     majorETFs = json.load(f)

    # We can get away with reusing the getStockPrice function again
    pass

@app.get("/stock-history/{ticker}")
def get_StockHistory(ticker: str, period: Period, interval: Interval):
    try:
        return getStockHistory(ticker, period, interval)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    

# fetch the data for each etf
# Fetch from this list



# Exploring ETFs (a safe way to invest for beginners?)\ (Grab a list of ETFs)


# Investing in bonds

