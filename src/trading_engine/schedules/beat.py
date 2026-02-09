from celery.schedules import crontab

beat_schedule = {
    # Fetch daily bars at 4:30 PM EST, Mon-Fri
    "fetch_prices_daily": {
        "task": "trading_engine.fetch_prices",
        "schedule": crontab(minute=30, hour=16, day_of_week="mon-fri"),
        "args": (),
    }
}