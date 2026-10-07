from celery.schedules import crontab

beat_schedule = {
    # Fetch prices -> evaluate strategies -> execute paper trades -> reconcile,
    # run in order inside one task at 4:30 PM ET, Mon-Fri. Market holidays are
    # skipped by the task itself; missing prices trigger a retry.
    "run_daily_pipeline": {
        "task": "trading_engine.run_daily_pipeline",
        "schedule": crontab(minute=30, hour=16, day_of_week="mon-fri"),
        "args": (),
    },
    # Add newly listed tickers (e.g. IPOs) to the stocks table, 7 AM ET Mon-Fri.
    # Idempotent: existing rows are untouched, a missed run is caught up next time.
    "sync_listings": {
        "task": "stocks.sync_listings",
        "schedule": crontab(minute=0, hour=7, day_of_week="mon-fri"),
        "args": (),
    },
}
