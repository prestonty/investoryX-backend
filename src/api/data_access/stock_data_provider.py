import httpx
from selectolax.parser import HTMLParser
import json
import numpy as np
import pandas as pd
# import asyncio
import yfinance as yf
# from src.models.requests import RequestHistory
from src.dataTypes.history import Period, Interval
from src.utils import dataframeToJson

def getStockPrice(ticker: str, etf:bool = False):
    try:
        if etf:
            url = f"https://stockanalysis.com/etf/{ticker}/"
        else:
            url = f"https://stockanalysis.com/stocks/{ticker}/"
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

        tickerSymbol = ticker.upper()

        return {"companyName": companyName, "tickerSymbol": tickerSymbol, "stockPrice": stockPrice, "priceChange": priceChange, "priceChangePercent": priceChangePercent}
    
    except httpx.RequestError as e:
        raise RuntimeError(f"Request failed: {str(e)}")
    except Exception as e:
        raise RuntimeError(f"Unexpected error: {str(e)}")

def getStockPrices(tickers):
    # Reduce the amount of calls, and add an artificial delay to respect the limit rate
    # Maximum fetch 30 stocks at once!!!
    pass

    # I should call this every morning to fetch the stocks and store them in a database so it can be used throughout the day!!!

def getStockHistory(ticker: str, period: Period, interval: Interval):
    try:
        stockData = yf.Ticker(ticker)
        history = stockData.history(period=period, interval=interval)

        history = history.reset_index() # Condex index (Date) into a column
        history = history.rename(columns={
            "Date": "date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume"
        })

        formatHistory = dataframeToJson(history)

        return {"data": formatHistory, "title": f"Stock Price for {ticker} with {period} period and {interval} interval"}
    except httpx.RequestError as e:
        raise RuntimeError(f"Request failed: {str(e)}")
    except Exception as e:
        raise RuntimeError(f"Unexpected error: {str(e)}")


def getStockOverview(ticker: str):
    try:
        url = f"https://stockanalysis.com/stocks/{ticker}/"
        response = httpx.get(url)
        html = response.text
        tree = HTMLParser(html)
        
        overview = ["Market Cap", "Revenue (ttm)", "Net Income (ttm)", "Shares Out", "ESP (ttm)", "PE Ratio", "Foward PE", "Dividend", "Ex-Dividend Date", "Volume", "Open", "Previous Close", "Day's Range", "52-Week Range", "Beta", "Analysts", "Price Target", "Earnings Date"]

        overviewNode = tree.css("td.font-semibold")
        for i in range(len(overviewNode)):
            overviewNode[i] = overviewNode[i].text().strip() # modify td
        result = dict(zip(overview, overviewNode))
        return result
    except httpx.RequestError as e:
        raise RuntimeError(f"Request failed: {str(e)}")
    except Exception as e:
        raise RuntimeError(f"Unexpected error: {str(e)}")

def getStockNews(max_articles: int = 20):
    try:
        url = 'https://stockanalysis.com/news/all-stocks/'
        response = httpx.get(url)
        html = response.text
        tree = HTMLParser(html)

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
                "headline": title,
                "url": articleLink,
                "image": img,
                "source": source,
                "datetime": postingTime,
                "tickers": stockTickers,
            }

            newsResults.append(newsResult)

            currentNewsCount += 1
            if currentNewsCount == max_articles:
                break

        return newsResults  # I should put a constraint on this
    except httpx.RequestError as e:
        raise RuntimeError(f"Request failed: {str(e)}")
    except Exception as e:
        raise RuntimeError(f"Unexpected error: {str(e)}")

