from fastapi import FastAPI
import httpx
from selectolax.parser import HTMLParser
import json

app = FastAPI()

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
@app.get("/stocks/{tickerSym}")
def getStockPrice(tickerSym: str):
    url = f"https://stockanalysis.com/stocks/{tickerSym}/"
    response = httpx.get(url)
    html = response.text
    tree = HTMLParser(html)

    companyNode = tree.css_first("h1")
    companyName = companyNode.text().split("(")[0].strip() if companyNode else "N/A"

    stockPriceNode = tree.css_first("main div.mx-auto div.flex-row div div.text-4xl")
    stockPrice = stockPriceNode.text() if stockPriceNode else "N/A"

    priceChangesNode = tree.css_first("main div.mx-auto div.flex-row div div.font-semibold")
    priceChanges = priceChangesNode.text().split(" ")
    priceChange = priceChanges[0] if priceChangesNode else "N/A"
    priceChangePercent = priceChanges[1][1:-1] if priceChangesNode else "N/A" # Use -2 if you want to remove the % symbol

    tickerSymbol = tickerSym.upper()

    return {"companyName": companyName, "tickerSymbol": tickerSymbol, "stockPrice": stockPrice, "priceChange": priceChange, "priceChangePercent": priceChangePercent}

# Get more advanced data from stock for display page
@app.get("/stock-overview/{tickerSym}")
def getStockOverview(tickerSym: str):
    url = f"https://stockanalysis.com/stocks/{tickerSym}/"
    response = httpx.get(url)
    html = response.text
    tree = HTMLParser(html)
    
    overview = ["Market Cap", "Revenue (ttm)", "Net Income (ttm)", "Shares Out", "ESP (ttm)", "PE Ratio", "Foward PE", "Dividend", "Ex-Dividend Date", "Volume", "Open", "Previous Close", "Day's Range", "52-Week Range", "Beta", "Analysts", "Price Target", "Earnings Date"]

    overviewNode = tree.css("td.font-semibold")
    for i in range(len(overviewNode)):
        overviewNode[i] = overviewNode[i].text().strip() # modify td
    result = dict(zip(overview, overviewNode))
    print(result)
    return result

# STOCK NEWS ---------------------------------------------------------------
@app.get("/stock-news")
def getStockNews():
    url = 'https://stockanalysis.com/news/all-stocks/'
    response = httpx.get(url)
    html = response.text
    tree = HTMLParser(html)

    MAX_NEWS_RESULTS = 20
    currentNewsCount = 0

    newsNodes = tree.css("main div div div div.gap-4")
    
    newsResults = []

    for node in newsNodes:
        anchorNode = node.css_first("a")
        articleLink = anchorNode.attributes["href"]
        
        imgNode = anchorNode.css_first("img")
        img = imgNode.attributes["src"]

        titleNode = node.css_first("h3")
        title = titleNode.text()

        stockTickerNodes = node.css("a.ticker")
        stockTickers = [stockTickerNode.text() for stockTickerNode in stockTickerNodes]
        
        detailsNode = node.css_first("div div.text-faded")
        details = detailsNode.text().split(" - ")
        postingTime = details[0]
        source = details[1]

        newsResult = {
            "title": title,
            "img": img,
            "articleLink": articleLink,
            "stockTickers": stockTickers,
            "postingTime": postingTime,
            "source": source,
        }

        newsResults.append(newsResult)

        currentNewsCount += 1
        if currentNewsCount == MAX_NEWS_RESULTS:
            break
    
    return newsResults # I should put a constraint on this

# Fetch market indices and it sprices (Dows Jones, NasDaq, NYSE)

# Exploring ETFs (a safe way to invest for beginners?)\


# Investing in bonds

