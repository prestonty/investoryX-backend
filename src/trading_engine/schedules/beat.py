from celery.schedules import crontab

beat_schedule = {
    # Fetch daily bars at 4:30 PM EST, Mon-Fri
    "fetch_prices_daily": {
        "task": "trading_engine.fetch_prices",
        "schedule": crontab(minute=30, hour=16, day_of_week="mon-fri"),
        "args": (),
    },
    # Evaluate strategy signals after price fetch.
    "evaluate_strategies_daily": {
        "task": "trading_engine.evaluate_strategies",
        "schedule": crontab(minute=40, hour=16, day_of_week="mon-fri"),
        "args": (),
    },
    # Execute pending paper trades after strategy evaluation.
    "execute_paper_trades_daily": {
        "task": "trading_engine.execute_paper_trades",
        "schedule": crontab(minute=50, hour=16, day_of_week="mon-fri"),
        "args": (),
    },
    # Reconcile simulator cash/positions after trade execution.
    "reconcile_portfolios_daily": {
        "task": "trading_engine.reconcile_portfolios",
        "schedule": crontab(minute=0, hour=17, day_of_week="mon-fri"),
        "args": (),
    },
}
