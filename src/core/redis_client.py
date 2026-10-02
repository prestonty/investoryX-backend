import logging
import os
import time
from urllib.parse import urlsplit, urlunsplit

import redis

logger = logging.getLogger("investoryx.redis")

# Fail fast: a slow or unreachable Redis must never make API requests hang.
CONNECT_TIMEOUT_SECONDS = 0.5
COMMAND_TIMEOUT_SECONDS = 0.5
# After a failure, skip Redis for this long instead of retrying on every request.
RETRY_AFTER_SECONDS = 30.0

_client: redis.Redis | None = None
_unavailable_until = 0.0


# Cache and rate-limit keys live in their own logical db so they can be flushed
# without touching Celery's queue (db 0). All of them have TTLs, so with
# maxmemory-policy volatile-lru they're evicted first and the queue never is.
CACHE_DB = 2


def _redis_url() -> str:
    explicit = os.getenv("CACHE_REDIS_URL")
    if explicit:
        return explicit
    base = os.getenv("REDIS_URL") or os.getenv("CELERY_BROKER_URL") or "redis://localhost:6379"
    parts = urlsplit(base)
    return urlunsplit((parts.scheme, parts.netloc, f"/{CACHE_DB}", parts.query, parts.fragment))


def get_redis() -> redis.Redis | None:
    """Shared Redis client, or None while Redis is unavailable (callers degrade gracefully)."""
    global _client
    if _client is not None:
        return _client
    if time.monotonic() < _unavailable_until:
        return None
    try:
        client = redis.from_url(
            _redis_url(),
            decode_responses=True,
            socket_connect_timeout=CONNECT_TIMEOUT_SECONDS,
            socket_timeout=COMMAND_TIMEOUT_SECONDS,
        )
        client.ping()
    except Exception as exc:
        mark_unavailable(exc)
        return None
    _client = client
    return _client


def mark_unavailable(exc: Exception) -> None:
    """Drop the client and back off; call this when a Redis command fails."""
    global _client, _unavailable_until
    _client = None
    _unavailable_until = time.monotonic() + RETRY_AFTER_SECONDS
    logger.warning("Redis unavailable, retrying in %ss: %s", int(RETRY_AFTER_SECONDS), exc)
