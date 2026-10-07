# Running the schedule manually

Celery Beat runs `trading_engine.run_daily_pipeline` at 4:30 PM ET on weekdays. It runs fetch prices -> evaluate strategies -> execute paper trades -> reconcile portfolios in order for the last completed trading day, skips market holidays, and retries (every 10 minutes, up to 3 times) if no prices come back.

It also runs `stocks.sync_listings` at 7 AM ET on weekdays, which adds newly listed tickers (e.g. IPOs) from Alpha Vantage to the `stocks` table. Existing rows are never changed, so it's safe to run any time.

Running the pipeline again for a day that was already evaluated is safe: evaluation skips simulators that already have signals for that day, so no duplicate trades are created.

### Example:

```
# Whole pipeline for the last completed trading day
docker compose exec celery-worker celery -A src.celery_app.app call trading_engine.run_daily_pipeline

# Whole pipeline for a specific trading day
docker compose exec celery-worker celery -A src.celery_app.app call trading_engine.run_daily_pipeline --args='["2026-02-18"]'

# Individual stages (each accepts a `day` keyword argument)
docker compose exec celery-worker python -c "from src.trading_engine.tasks.fetch_prices import fetch_prices; print(fetch_prices(day='2026-02-18'))"
docker compose exec celery-worker celery -A src.celery_app.app call trading_engine.evaluate_strategies --kwargs='{"day": "2026-02-18"}'
docker compose exec celery-worker celery -A src.celery_app.app call trading_engine.execute_paper_trades --kwargs='{"day": "2026-02-18"}'
docker compose exec celery-worker celery -A src.celery_app.app call trading_engine.reconcile_portfolios

# Pick up new listings now instead of waiting for 7 AM
docker compose exec celery-worker celery -A src.celery_app.app call stocks.sync_listings

docker compose logs -f --tail=200 celery-worker
```
