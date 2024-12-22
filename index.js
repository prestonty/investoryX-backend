const dotenv = require("dotenv");
const finnhub = require("finnhub");
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

app.get("/getNews", (req, res) => {
    // fetch the news
    finnhubClient.marketNews("general", {}, (error, data, response) => {
        // console.log(data);
        console.log("Successfully fetched the data");
    });
});

// Fetch latest news
