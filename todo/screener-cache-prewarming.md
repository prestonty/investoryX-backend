# Screener Cache Pre-warming via Celery Beat

## What problem does this solve?

With Option 3 (Redis caching), the **first request** after a cache miss still hits Yahoo Finance and
takes 10-20 seconds. This happens on:
- Server cold start
- Every 5 minutes when the TTL expires
- After a Redis restart

Pre-warming eliminates cold starts by running a **scheduled Celery task** that refreshes the cache
*before* it expires. The HTTP endpoint never calls Yahoo Finance — it always reads from Redis.

```
Without pre-warming:          With pre-warming:
Request → cache miss          Celery beat (every 4 min) → Yahoo Finance → Redis
         → Yahoo Finance                ↓
         → 10-20s wait        Any request → Redis → < 1ms
         → store in Redis
```

---

## What needs to be built

### 1. Celery task — `src/api/tasks/screener_tasks.py` (new file)

Create three Celery tasks, one per screener, that call the existing service functions and force a
cache refresh. The tasks bypass the cache check and write directly so the result is always fresh.

```python
from src.celery_app import app
from src.api.services.stock_data_service import _cache_set, SCREENER_CACHE_TTL
import yfinance as yf
from src.utils import round_2_decimals

@app.task(name="tasks.refresh_day_gainers")
def refresh_day_gainers(limit: int = 8, min_price: float = 4.0):
    result = yf.screen('day_gainers', count=limit * 4)
    # ... same filtering logic as getTopGainers ...
    _cache_set(f"day_gainers:{limit}:{min_price}", valid)

@app.task(name="tasks.refresh_day_losers")
def refresh_day_losers(limit: int = 8, min_price: float = 4.0): ...

@app.task(name="tasks.refresh_most_actives")
def refresh_most_actives(limit: int = 8, min_price: float = 4.0): ...
```

**Important:** To avoid duplicating the filtering logic, extract a shared
`_fetch_screener(screen_name, limit, min_price)` helper in `stock_data_service.py` that both
the service functions and the Celery tasks call.

### 2. Celery Beat schedule — `src/celery_app.py`

Add a `beat_schedule` to the existing Celery app config. Run every 4 minutes so the cache
(TTL = 5 min) is always refreshed before it expires:

```python
app.conf.beat_schedule = {
    "refresh-day-gainers": {
        "task": "tasks.refresh_day_gainers",
        "schedule": 240.0,  # every 4 minutes
        "args": (8, 4.0),
    },
    "refresh-day-losers": {
        "task": "tasks.refresh_day_losers",
        "schedule": 240.0,
        "args": (8, 4.0),
    },
    "refresh-most-actives": {
        "task": "tasks.refresh_most_actives",
        "schedule": 240.0,
        "args": (8, 4.0),
    },
}
```

### 3. Register the task module — `src/celery_app.py`

Add `"src.api.tasks.screener_tasks"` to the `include` list so Celery discovers the new tasks.

### 4. Startup warm — `src/main.py` (optional but recommended)

On application startup, trigger each refresh task once so the cache is warm immediately, rather
than waiting up to 4 minutes for the first scheduled run:

```python
@app.on_event("startup")
async def warm_screener_cache():
    from src.api.tasks.screener_tasks import (
        refresh_day_gainers, refresh_day_losers, refresh_most_actives
    )
    refresh_day_gainers.delay()
    refresh_day_losers.delay()
    refresh_most_actives.delay()
```

### 5. Run Celery Beat

Celery Beat must be running alongside the FastAPI server and the Celery worker:

```bash
# Terminal 1: FastAPI
uvicorn src.main:app --reload

# Terminal 2: Celery worker
celery -A src.celery_app worker --loglevel=info

# Terminal 3: Celery beat scheduler
celery -A src.celery_app beat --loglevel=info
```

In Docker/production, add a `celery-beat` service to `docker-compose.yml`.

---

## Files to modify / create

| File | Change |
|------|--------|
| `src/api/tasks/screener_tasks.py` | **New** — three refresh tasks |
| `src/api/services/stock_data_service.py` | Extract `_fetch_screener()` helper to avoid duplication |
| `src/celery_app.py` | Add `beat_schedule`, add task module to `include` |
| `src/main.py` | Add startup warm-up event (optional) |
| `docker-compose.yml` | Add `celery-beat` service |

---

## Market hours consideration

Yahoo Finance screeners return stale data outside of market hours (9:30am–4pm ET).
Consider only running the beat schedule during market hours to avoid unnecessary Yahoo Finance
calls and stale cache refreshes:

```python
from celery.schedules import crontab

"refresh-day-gainers": {
    "task": "tasks.refresh_day_gainers",
    "schedule": crontab(minute="*/4", hour="9-16", day_of_week="1-5"),
}
```