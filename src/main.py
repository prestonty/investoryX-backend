import os
from fastapi import FastAPI, HTTPException, Query, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Annotated
from dotenv import load_dotenv
import json
from pathlib import Path
import asyncio
import logging
from alembic.config import Config
from alembic import command

from src.dataTypes.history import Period, Interval

# Create the tables if they do not exist
from src.api.database.database import engine, Base


from src.models.requests import EmailRequest
from src.api.routes import stocks, users, watchlist, auth, simulator

# Services
from src.api.services.stock_data_service import *
from src.api.services.email_service import *

# Load environment variables
load_dotenv()

origins = [
    "https://investory-six.vercel.app",
    os.getenv("FRONTEND_BASE_URL"),
    "https://www.investoryx.ca",
]

app = FastAPI()
DEBUG_ERRORS = os.getenv("DEBUG_ERRORS", "false").lower() in ("1", "true", "yes")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("investoryx")

@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info("Request start %s %s", request.method, request.url.path)
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled error %s %s", request.method, request.url.path)
        raise
    logger.info("Request end %s %s -> %s", request.method, request.url.path, response.status_code)
    return response

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception during request: %s %s", request.method, request.url.path)
    if DEBUG_ERRORS:
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc), "error_type": exc.__class__.__name__},
        )
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
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
app.include_router(auth.router)
app.include_router(simulator.router)


# File Paths --------------------------------------------------------------------------------------
NAME = "market_index_ETFs_2.json"
ETF_PATH = Path(__file__).resolve().parent / "stocklist" / NAME

# DB Start up after deploying
@app.on_event("startup")
async def run_migrations():
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")


# STOCK INFO FUNCTIONS ----------------------------------------------------------------------------------

# https://fastapi.tiangolo.com/tutorial/security/first-steps/#use-it
# Add OAuth to your methods so user can use the only when logged in (to some, e.g. watchlist)

# Get stock info function - returns all the stock information from the page (heavy function)
@app.get("/stocks/{ticker}")
def get_StockPrice(ticker: str):
    """
    Get basic information about a stock - company name, price, price change from its ticker symbol

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
    """
    Get advanced information about a stock from its ticker symbol

    Args:
        ticker (str): The ticker symbol of the stock

    Returns:
        dict: Stock information if found, else raises HTTPException.
    """
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
    

# ETFS -----------------------------------------------------------------------------------
@app.get("/get-default-indexes")
def get_DefaultIndexes():
    """
    Get a list of default market index etfs to display on the homepage.
    
    Returns:
        dict: A list of default market indexes.
    """

    try:
        with ETF_PATH.open("r", encoding="utf-8") as f:
            default_etfs = json.load(f)
    except FileNotFoundError:
        # In dev, exposing the resolved path helps; in prod, log it instead.
        raise HTTPException(404, detail=f"Default ETF file not found at {ETF_PATH}")
    except json.JSONDecodeError as e:
        raise HTTPException(500, detail=f"Invalid JSON in {ETF_PATH}: {e}")


    try:
        return getDefaultIndexes(default_etfs)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


# MARKET MOVERS -----------------------------------------------------------------------------------
@app.get("/top-gainers")
def get_TopGainers(limit: int = Query(default=5, description="Number of top gainers to return")):
    """
    Get top gainers (stocks with highest percentage gains).
    
    Args:
        limit (int): Number of top gainers to return (default: 5)
    
    Returns:
        list: List of top gainers with ticker, price, change, and changePercent.
    """
    try:
        return getTopGainers(limit)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/top-losers")
def get_TopLosers(limit: int = Query(default=5, description="Number of top losers to return")):
    """
    Get top losers (stocks with highest percentage losses).
    
    Args:
        limit (int): Number of top losers to return (default: 5)
    
    Returns:
        list: List of top losers with ticker, price, change, and changePercent.
    """
    try:
        return getTopLosers(limit)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/most-active")
def get_MostActive(limit: int = Query(default=5, description="Number of most active stocks to return")):
    """
    Get most actively traded stocks (highest volume).
    
    Args:
        limit (int): Number of most active stocks to return (default: 5)
    
    Returns:
        list: List of most active stocks with ticker, price, change, changePercent, and volume.
    """
    try:
        return getMostActive(limit)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

# EMAIL SERVICE -----------------------------------------------------------------------------------
@app.post("/send-sign-up-email")
def send_SignUpEmail(request: EmailRequest):
    try:
        return sendSignUpEmail(request.email, request.first_name, request.verification_url)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/send-welcome-email")
def send_WelcomeEmail(email: str, first_name: str, dashboard_url: str):
    try:
        return sendWelcomeEmail(email, first_name, dashboard_url)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))




# fetch the data for each etf
# Fetch from this list



# Exploring ETFs (a safe way to invest for beginners?)\ (Grab a list of ETFs)


# Investing in bonds

