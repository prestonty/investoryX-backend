import httpx
from selectolax.parser import HTMLParser
import time
import numpy as np
import pandas as pd
import yfinance as yf
from src.dataTypes.history import Period, Interval
from src.utils import dataframeToJson, with_backoff, round_2_decimals, RateLimiter

# Rate limiting
per_batch_limiter  = RateLimiter(20, 60.0)
per_ticker_limiter = RateLimiter(60, 60.0)

def getStockPriceYFinance(ticker: str, etf: bool = False):
    """
    Get stock price data using yfinance library (more reliable)
    """
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        
        # Get current price and previous close
        current_price = info.get('currentPrice', info.get('regularMarketPrice', 'N/A'))
        previous_close = info.get('previousClose', 'N/A')
        
        # Calculate price change
        if current_price != 'N/A' and previous_close != 'N/A':
            price_change = current_price - previous_close
            price_change_percent = (price_change / previous_close) * 100
            price_change_str = f"{price_change:.2f}"
            price_change_percent_str = f"{price_change_percent:.2f}"
        else:
            price_change_str = "N/A"
            price_change_percent_str = "N/A"
        
        # Get company name
        company_name = info.get('longName', info.get('shortName', 'N/A'))
        
        return {
            "companyName": company_name,
            "tickerSymbol": ticker.upper(),
            "stockPrice": f"{current_price:.2f}" if current_price != 'N/A' else "N/A",
            "priceChange": price_change_str,
            "priceChangePercent": price_change_percent_str
        }

    except Exception as e:
        raise RuntimeError(f"Failed to fetch stock data via yfinance: {str(e)}")


def getStockPriceWebScraping(ticker: str, etf: bool = False):
    """
    Get stock price data using web scraping (original method)
    """
    try:
        url = f"https://stockanalysis.com/etf/{ticker}/" if etf else f"https://stockanalysis.com/stocks/{ticker}/"
        response = httpx.get(url)

        if response.status_code != 200:
            raise RuntimeError(f"Failed to fetch stock page (status {response.status_code})")

        html = response.text
        tree = HTMLParser(html)

        companyNode = tree.css_first("h1")
        companyName = companyNode.text().split("(")[0].strip() if companyNode else "N/A"

        stockPriceNode = tree.css_first("main div.mx-auto div.flex-row div div.text-4xl")
        stockPrice = stockPriceNode.text() if stockPriceNode else "N/A"

        priceChangesNode = tree.css_first("main div.mx-auto div.flex-row div div.font-semibold")
        priceChanges = priceChangesNode.text().split(" ") if priceChangesNode else ["N/A", "(N/A%)"]
        priceChange = priceChanges[0]
        priceChangePercent = priceChanges[1][1:-1] if len(priceChanges) > 1 else "N/A"

        tickerSymbol = ticker.upper()

        return {
            "companyName": companyName,
            "tickerSymbol": tickerSymbol,
            "stockPrice": stockPrice,
            "priceChange": priceChange,
            "priceChangePercent": priceChangePercent
        }

    except httpx.RequestError as e:
        raise RuntimeError(f"Request failed: {str(e)}")
    except Exception as e:
        raise RuntimeError(f"Unexpected error: {str(e)}")


def getStockPrice(ticker: str, etf: bool = False):
    """
    Get stock price data with fallback mechanism
    Tries yfinance first, falls back to web scraping if needed
    """
    try:
        # Try yfinance first (more reliable)
        return getStockPriceYFinance(ticker, etf)
    except Exception as e:
        print(f"yfinance failed for {ticker}: {str(e)}")
        try:
            # Fallback to web scraping
            return getStockPriceWebScraping(ticker, etf)
        except Exception as web_error:
            raise RuntimeError(f"Both yfinance and web scraping failed for {ticker}. yfinance error: {str(e)}, web scraping error: {str(web_error)}")


def getStockPricesBatch(tickers):
    """
    Fetches stock prices for multiple tickers using yfinance.
    Respects Yahoo Finance's limit of ~30 tickers per batch.
    Add throttling to avoid rate limits
    """
    results = {}
    # Yahoo Finance handles up to ~30 tickers at once
    for i in range(0, len(tickers), 30):
        batch = tickers[i:i + 30]
        tickers_str = " ".join(batch)

        # Wait up to 5s for a batch slot; if not, back off a bit
        if not per_batch_limiter.wait(timeout=5):
            time.sleep(1)  # or raise/return partial/etc.
        data = with_backoff(lambda: yf.Tickers(tickers_str))

        for t in batch:
            # Wait up to 2s per ticker; if not available, skip and try next
            if not per_ticker_limiter.wait(timeout=2):
                results[t] = {"error": "rate limited, try later"}
                continue

            def fetch_one():
                info = data.tickers[t].fast_info
                last_price = info.last_price
                prev_close = info.previous_close
                pct = ((last_price - prev_close) / prev_close) * 100 if prev_close else None
                return {
                    "stockPrice": last_price,
                    "priceChange": None if prev_close is None else (last_price - prev_close),
                    "priceChangePercent": pct,
                }

            try:
                results[t] = with_backoff(fetch_one)
            except Exception as e:
                results[t] = {"error": str(e)}

    return results

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


def getStockOverviewYFinance(ticker: str):
    """
    Get stock overview data using yfinance library
    """
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        
        # Map yfinance data to our expected format
        overview = {}
        
        # Helper function to format numbers safely
        def format_number(value, prefix="", suffix="", decimal_places=2):
            if value is None or value == 'N/A':
                return "N/A"
            try:
                if isinstance(value, (int, float)):
                    if decimal_places == 0:
                        return f"{prefix}{value:,}{suffix}"
                    else:
                        return f"{prefix}{value:,.{decimal_places}f}{suffix}"
                return str(value)
            except:
                return "N/A"
        
        overview["Market Cap"] = format_number(info.get('marketCap'), "$")
        overview["Revenue (ttm)"] = format_number(info.get('totalRevenue'), "$")
        overview["Net Income (ttm)"] = format_number(info.get('netIncomeToCommon'), "$")
        overview["Shares Out"] = format_number(info.get('sharesOutstanding'), "", "", 0)
        overview["ESP (ttm)"] = format_number(info.get('trailingEps'), "$")
        overview["PE Ratio"] = format_number(info.get('trailingPE'))
        overview["Foward PE"] = format_number(info.get('forwardPE'))
        overview["Dividend"] = format_number(info.get('dividendRate'), "$")
        overview["Ex-Dividend Date"] = str(info.get('exDividendDate', 'N/A'))
        overview["Volume"] = format_number(info.get('volume'), "", "", 0)
        overview["Open"] = format_number(info.get('open'), "$")
        overview["Previous Close"] = format_number(info.get('previousClose'), "$")
        
        # Handle ranges
        day_low = info.get('dayLow')
        day_high = info.get('dayHigh')
        if day_low and day_high:
            overview["Day's Range"] = f"${day_low:.2f} - ${day_high:.2f}"
        else:
            overview["Day's Range"] = "N/A"
            
        week_low = info.get('fiftyTwoWeekLow')
        week_high = info.get('fiftyTwoWeekHigh')
        if week_low and week_high:
            overview["52-Week Range"] = f"${week_low:.2f} - ${week_high:.2f}"
        else:
            overview["52-Week Range"] = "N/A"
            
        overview["Beta"] = format_number(info.get('beta'))
        overview["Analysts"] = format_number(info.get('numberOfAnalystOpinions'), "", "", 0)
        overview["Price Target"] = format_number(info.get('targetMeanPrice'), "$")
        overview["Earnings Date"] = str(info.get('earningsTimestamp', 'N/A'))
        
        return overview
    except Exception as e:
        raise RuntimeError(f"Failed to fetch stock overview data via yfinance: {str(e)}")

def getStockOverviewWebScraping(ticker: str):
    """
    Get stock overview data using web scraping (original method)
    """
    try:
        url = f"https://stockanalysis.com/stocks/{ticker}/"
        response = httpx.get(url)
        
        if response.status_code != 200:
            raise RuntimeError(f"Failed to fetch stock overview page (status {response.status_code})")
            
        html = response.text
        tree = HTMLParser(html)
        
        overview = ["Market Cap", "Revenue (ttm)", "Net Income (ttm)", "Shares Out", "ESP (ttm)", "PE Ratio", "Foward PE", "Dividend", "Ex-Dividend Date", "Volume", "Open", "Previous Close", "Day's Range", "52-Week Range", "Beta", "Analysts", "Price Target", "Earnings Date"]

        overviewNode = tree.css("td.font-semibold")
        
        # Debug: Print the number of nodes found
        print(f"Found {len(overviewNode)} overview nodes for {ticker}")
        
        # Ensure we have enough nodes
        if len(overviewNode) < len(overview):
            print(f"Warning: Expected {len(overview)} nodes but found {len(overviewNode)}")
            # Pad with empty strings if we don't have enough nodes
            while len(overviewNode) < len(overview):
                overviewNode.append("N/A")
        
        # Extract text from nodes
        overviewValues = []
        for i in range(len(overview)):
            if i < len(overviewNode):
                value = overviewNode[i].text().strip()
                overviewValues.append(value if value else "N/A")
            else:
                overviewValues.append("N/A")
        
        result = dict(zip(overview, overviewValues))
        
        # Debug: Print the result
        print(f"Overview data for {ticker}: {result}")
        
        return result
    except httpx.RequestError as e:
        raise RuntimeError(f"Request failed: {str(e)}")
    except Exception as e:
        raise RuntimeError(f"Unexpected error: {str(e)}")

def getStockOverview(ticker: str):
    """
    Get stock overview data with fallback mechanism
    Tries yfinance first, falls back to web scraping if needed
    """
    try:
        # Try yfinance first (more reliable)
        return getStockOverviewYFinance(ticker)
    except Exception as e:
        print(f"yfinance overview failed for {ticker}: {str(e)}")
        try:
            # Fallback to web scraping
            return getStockOverviewWebScraping(ticker)
        except Exception as web_error:
            raise RuntimeError(f"Both yfinance and web scraping failed for {ticker} overview. yfinance error: {str(e)}, web scraping error: {str(web_error)}")

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

def getDefaultIndexes(default_etfs):
    """
    Get default market index etfs from a predefined list
    """
    try:
        if not default_etfs:
            raise ValueError("No default ETFs provided")
        tickers = {etf["ticker"] for cat in default_etfs for etf in cat["etfs"]}
        prices = getStockPricesBatch(list(tickers))

        for category in default_etfs:
            for etf in category["etfs"]:
                p = prices.get(etf["ticker"])
                if p:
                    etf["price"] = round_2_decimals(p["stockPrice"])
                    etf["priceChange"] = round_2_decimals(p["priceChange"])
                    etf["priceChangePercent"] = round_2_decimals(p["priceChangePercent"])


        return default_etfs
    except Exception as e:
        raise RuntimeError(f"Failed to fetch default ETFs: {str(e)}")


def getTopGainers(limit: int = 5):
    """
    Get top 5 gainers (stocks with highest percentage gains)
    Uses yfinance to fetch data for major market movers
    """
    try:
        # For now, we'll use a curated list of major stocks to check for gainers
        # In production, you might want to use a more comprehensive list
        major_stocks = [
            "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "META", "NVDA", "NFLX", 
            "AMD", "INTC", "CRM", "ORCL", "ADBE", "PYPL", "UBER", "LYFT",
            "ZM", "SHOP", "SQ", "ROKU", "SPOT", "SNAP", "TWTR", "PINS"
        ]
        
        # Get batch prices for major stocks
        prices = getStockPricesBatch(major_stocks)
        
        # Filter out errors and calculate percentage changes
        valid_stocks = []
        for ticker, data in prices.items():
            if "error" not in data and data.get("priceChangePercent") is not None:
                valid_stocks.append({
                    "ticker": ticker,
                    "price": data["stockPrice"],
                    "change": data["priceChange"],
                    "changePercent": data["priceChangePercent"]
                })
        
        # Sort by percentage change (highest first) and take top 5
        top_gainers = sorted(valid_stocks, key=lambda x: x["changePercent"], reverse=True)[:limit]
        
        return top_gainers
        
    except Exception as e:
        raise RuntimeError(f"Failed to fetch top gainers: {str(e)}")


def getTopLosers(limit: int = 5):
    """
    Get top 5 losers (stocks with highest percentage losses)
    Uses yfinance to fetch data for major market movers
    """
    try:
        # For now, we'll use a curated list of major stocks to check for losers
        # In production, you might want to use a more comprehensive list
        major_stocks = [
            "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "META", "NVDA", "NFLX", 
            "AMD", "INTC", "CRM", "ORCL", "ADBE", "PYPL", "UBER", "LYFT",
            "ZM", "SHOP", "SQ", "ROKU", "SPOT", "SNAP", "TWTR", "PINS"
        ]
        
        # Get batch prices for major stocks
        prices = getStockPricesBatch(major_stocks)
        
        # Filter out errors and calculate percentage changes
        valid_stocks = []
        for ticker, data in prices.items():
            if "error" not in data and data.get("priceChangePercent") is not None:
                valid_stocks.append({
                    "ticker": ticker,
                    "price": data["stockPrice"],
                    "change": data["priceChange"],
                    "changePercent": data["priceChangePercent"]
                })
        
        # Sort by percentage change (lowest first) and take top 5
        top_losers = sorted(valid_stocks, key=lambda x: x["changePercent"])[:limit]
        
        return top_losers
        
    except Exception as e:
        raise RuntimeError(f"Failed to fetch top losers: {str(e)}")


def getMostActive(limit: int = 5):
    """
    Get top 5 most actively traded stocks (highest volume)
    Uses yfinance to fetch volume data for major stocks
    """
    try:
        # For now, we'll use a curated list of major stocks to check for volume
        # In production, you might want to use a more comprehensive list
        major_stocks = [
            "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "META", "NVDA", "NFLX", 
            "AMD", "INTC", "CRM", "ORCL", "ADBE", "PYPL", "UBER", "LYFT",
            "ZM", "SHOP", "SQ", "ROKU", "SPOT", "SNAP", "TWTR", "PINS"
        ]
        
        # Get batch prices for major stocks
        prices = getStockPricesBatch(major_stocks)
        
        # Filter out errors and get volume data
        valid_stocks = []
        for ticker, data in prices.items():
            if "error" not in data:
                # Get additional volume data for each stock
                try:
                    stock = yf.Ticker(ticker)
                    info = stock.info
                    volume = info.get('volume', 0)
                    
                    valid_stocks.append({
                        "ticker": ticker,
                        "price": data["stockPrice"],
                        "change": data["priceChange"],
                        "changePercent": data["priceChangePercent"],
                        "volume": volume
                    })
                except:
                    continue
        
        # Sort by volume (highest first) and take top 5
        most_active = sorted(valid_stocks, key=lambda x: x["volume"], reverse=True)[:limit]
        
        return most_active
        
    except Exception as e:
        raise RuntimeError(f"Failed to fetch most active stocks: {str(e)}")