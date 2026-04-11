---
description: Populate the stocks database by downloading listing data from Alpha Vantage and inserting it into the database.
---

Run the stock data population script to download stock listings from Alpha Vantage and insert them into the database.

Steps:
1. Make sure the backend Docker container is running (`docker compose up -d` from `investoryx-backend/`).
2. Run the script inside the container:

```bash
docker compose exec backend python -m src.api.database.populateStockData
```

If you want to run it locally (outside Docker), make sure your virtual environment is active and run from the `investoryx-backend/` directory:

```bash
poetry run python -m src.api.database.populateStockData
```

The script will:
- Download the CSV listing from Alpha Vantage (`LISTING_STATUS` endpoint)
- Parse each row and skip entries with missing `symbol`, `name`, `exchange`, or `assetType`
- Skip tickers already present in the database (no duplicates)
- Insert in batches of 1000 and print progress
- Print a final summary of inserted vs skipped counts