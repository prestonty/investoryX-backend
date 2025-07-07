from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import json

from api.dataAccess.stockScraper import *
from dataTypes.history import Period, Interval


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # or ["*"] for dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Hello, FastAPI!"}

@app.get("/getNews")
def getNews():
    pass

# SEARCH FUNCTIONS --------------------------------------------------------------------------------------

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
def get_StockNews():
    try:
        return getStockNews()
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

