import os
from celery import Celery
from src.trading_engine.schedules.beat import beat_schedule


_redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
broker_url = os.getenv("CELERY_BROKER_URL", f"{_redis_url}/0")
# Task results (e.g. backtest results) are stored in Postgres so they survive
# Redis restarts/eviction and stay available after the worker finishes.
result_backend = os.getenv("CELERY_RESULT_BACKEND") or f"db+{os.getenv('DATABASE_URL', '')}"
timezone = os.getenv("CELERY_TIMEZONE", "America/New_York")

app = Celery(
    "investoryx",
    broker=broker_url,
    backend=result_backend,
    include=[
        "src.trading_engine.tasks.fetch_prices",
        "src.trading_engine.tasks.evaluate_strategies",
        "src.trading_engine.tasks.execute_paper_trades",
        "src.trading_engine.tasks.fill_queued_orders",
        "src.trading_engine.tasks.reconcile_portfolios",
        "src.trading_engine.tasks.run_backtest",
        "src.trading_engine.tasks.daily_pipeline",
        "src.trading_engine.tasks.sync_listings",
    ]
)

app.conf.update(
    enable_utc=False,
    timezone=timezone,
    task_track_started=True,
    task_send_sent_event=True,
    # Kept 30 days; Celery Beat's built-in backend_cleanup task deletes older rows.
    result_expires=60 * 60 * 24 * 30,
)

_beat_enabled = os.getenv("CELERY_BEAT_ENABLED", "true").lower() in ("1", "true", "yes")
app.conf.beat_schedule = beat_schedule if _beat_enabled else {}
