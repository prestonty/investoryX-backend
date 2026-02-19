# Running the schedule manually

Run this command to manually execute the tasks. You need to switch out the date for a valid day with data in the stock market. E.g. Today or Yesterday

### Example:

```
docker compose exec celery-worker python -c "from src.trading_engine.tasks.fetch_prices import fetch_prices; print(fetch_prices(day='2026-02-18'))"

docker compose exec celery-worker celery -A src.celery_app.app call trading_engine.evaluate_strategies
docker compose exec celery-worker celery -A src.celery_app.app call trading_engine.execute_paper_trades
docker compose exec celery-worker celery -A src.celery_app.app call trading_engine.reconcile_portfolios
docker compose logs -f --tail=200 celery-worker

```