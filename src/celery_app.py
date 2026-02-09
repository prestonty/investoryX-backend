import os
from celery import Celery
from src.trading_engine.schedules.beat import beat_schedule


broker_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
timezone = os.getenv("CELERY_TIMEZONE", "America/New_York")

app = Celery(
    "investoryx",
    broker=broker_url,
    backend=result_backend,
    include=["src.trading_engine.tasks"],
)

app.conf.update(
    enable_utc=False,
    timezone=timezone,
    task_track_started=True,
    task_send_sent_event=True,
    result_expires=60 * 60 * 24,
)

app.config.beat_schedule = beat_schedule