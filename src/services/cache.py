"""Redis caching for market data, so page views don't each hit Yahoo / stockanalysis.com.

Fresh copies expire on a market-hours-aware TTL. A longer-lived "stale" copy is
kept too: if the upstream call fails (rate limited, scraper broken), the last
good value is served instead of an error. Cache misses never break requests:
without Redis, calls simply go upstream.
"""

import functools
import json
import logging
from datetime import datetime
from typing import Any, Callable

from src.core.redis_client import get_redis, mark_unavailable
from src.trading_engine.services.pricing import MARKET_TZ, _is_trading_day

logger = logging.getLogger("investoryx.cache")

STALE_TTL_SECONDS = 24 * 60 * 60

TTL = int | Callable[..., int]


def market_is_open(now: datetime | None = None) -> bool:
    """Regular NYSE session (9:30-16:00 ET on trading days)."""
    now_et = (now or datetime.now(MARKET_TZ)).astimezone(MARKET_TZ)
    minutes = now_et.hour * 60 + now_et.minute
    return _is_trading_day(now_et.date()) and 9 * 60 + 30 <= minutes < 16 * 60


def is_cacheable(value: Any) -> bool:
    """Don't cache empty results or overviews where every field failed ("N/A")."""
    if value is None:
        return False
    if isinstance(value, (list, dict)) and not value:
        return False
    if isinstance(value, dict) and all(v in ("N/A", None) for v in value.values()):
        return False
    return True


def _record(outcome: str, namespace: str) -> None:
    client = get_redis()
    if client is None:
        return
    try:
        client.incr(f"stats:cache:{outcome}:{namespace}")
    except Exception as exc:
        mark_unavailable(exc)


def cache_get(key: str) -> Any | None:
    client = get_redis()
    if client is None:
        return None
    try:
        raw = client.get(key)
        return json.loads(raw) if raw else None
    except Exception as exc:
        mark_unavailable(exc)
        return None


def cache_get_many(keys: list[str]) -> list[Any | None]:
    client = get_redis()
    if client is None or not keys:
        return [None] * len(keys)
    try:
        return [json.loads(raw) if raw else None for raw in client.mget(keys)]
    except Exception as exc:
        mark_unavailable(exc)
        return [None] * len(keys)


def cache_set(key: str, value: Any, ttl_seconds: int) -> None:
    client = get_redis()
    if client is None:
        return
    try:
        payload = json.dumps(value, default=str)
        pipe = client.pipeline()
        pipe.setex(f"cache:{key}", ttl_seconds, payload)
        pipe.setex(f"stale:{key}", max(ttl_seconds, STALE_TTL_SECONDS), payload)
        pipe.execute()
    except Exception as exc:
        mark_unavailable(exc)


def _resolve(ttl: TTL, args: tuple, kwargs: dict) -> int:
    return ttl(*args, **kwargs) if callable(ttl) else ttl


def cached(namespace: str, ttl_open: TTL, ttl_closed: TTL, key: Callable[..., str]):
    """Cache a function's JSON-serializable result in Redis.

    `key(*args, **kwargs)` builds the per-call key; TTLs may be ints or
    callables taking the same arguments (e.g. to depend on a chart interval).
    """

    def decorator(fn: Callable):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            cache_key = f"{namespace}:{key(*args, **kwargs)}"
            fresh = cache_get(f"cache:{cache_key}")
            if fresh is not None:
                _record("hit", namespace)
                return fresh
            _record("miss", namespace)

            try:
                value = fn(*args, **kwargs)
            except Exception:
                stale = cache_get(f"stale:{cache_key}")
                if stale is not None:
                    logger.warning("Upstream failed for %s; serving stale cache", cache_key)
                    _record("stale", namespace)
                    return stale
                raise

            if is_cacheable(value):
                ttl = _resolve(ttl_open if market_is_open() else ttl_closed, args, kwargs)
                cache_set(cache_key, value, ttl)
            return value

        return wrapper

    return decorator
