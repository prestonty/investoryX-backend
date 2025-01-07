'use strict'

const dotenv = require("dotenv");
const finnhub = require("finnhub");
const request = require("request");
const express = require("express");
const cors = require("cors");

dotenv.config();
const app = express();
const port = 5000;
app.use(cors());

app.use(
    cors({
        origin: "http://localhost:3000", // Frontend URL
    })
);

// Set up Finnhub client
const api_key = finnhub.ApiClient.instance.authentications["api_key"];
api_key.apiKey = process.env.FINNHUB_API_KEY;
const finnhubClient = new finnhub.DefaultApi();

app.get("/", (req, res) => {
    res.send("Hello World!");
});

app.listen(port, () => {
    console.log(`Investory backend listening on port ${port}`);
});

// Used in the dashboard to see the first 3 big articles
app.get("/getTopNews", (req, res) => {
    // fetch the news
    finnhubClient.marketNews("general", {}, (error, data, response) => {
        if (error) {
            console.error("Finnhub API Error:", error); // Log the actual error
            res.status(500).json({ error: "Failed to fetch news" });
        } else {
            console.log("Successfully fetched the top news");
            const firstFewArticles = data.slice(0, 3);
            res.json(firstFewArticles); // Send fetched data back to the client
        }
    });
});

// Used in the latest news page
app.get("/getNews", (req, res) => {
    // fetch the news
    finnhubClient.marketNews("general", {}, (error, data, response) => {
        if (error) {
            res.status(500).json({ error: "Failed to fetch news" });
        } else {
            console.log("Successfully fetched the news");
            // const articles = data.slice(0, 20);
            res.json(data); // Send fetched data back to the client
        }
    });
});

// Fetch Market Indices
app.get("/getIndices", async (req, res) => {
    const symbols = ["^GSPC", "^DJI", "^IXIC", "^NYA", "^XAX", "^BUK100P", "^RUT"];

    try {
        // Create an array of promises for each symbol
        const promises = symbols.map(symbol => {
            return new Promise((resolve, reject) => {
                finnhubClient.quote(symbol, (error, data, response) => {
                    if (error) {
                        reject({ symbol, error });
                    } else {
                        resolve({ symbol, data });
                    }
                });
            });
        });

        // Wait for all promises to resolve
        const results = await Promise.all(promises);

        // Send the results as a response
        res.json(results);
    } catch (error) {
        console.error("Error fetching indices:", error);
        res.status(500).json({ error: "Failed to fetch indices", details: error });
    }
});

// app.get("/getQuotes", (req, res) => {
//     finnhubClient.quote(req.)
// });


app.get("/getTopGainersLosers", (req, res) => {
    let url = 'https://www.alphavantage.co/query?function=TOP_GAINERS_LOSERS&apikey=6K3LBRGQSVWFLNLK';
    request.get({
        url: url,
        json: true,
        headers: {'User-Agent': 'request'}
      }, (error, response, data) => {
        if (error) {
            console.error("Error fetching data:", error);
            res.status(500).json({ error: "Failed to fetch data from Alpha Vantage" });
        } else if (res.statusCode !== 200) {
            console.error("Unexpected status code: ", response.statusCode);
            res.status(response.statusCode).json({error: "Unexpected status code from Alpha Vantage"});
        } else {
            // successfully send back the top 5 of each in json
          res.json({
            top_gainers: data.top_gainers.slice(0,5),
            top_losers: data.top_losers.slice(0,5),
          });
        }
    });
});