import threading
import time

from fastapi import HTTPException, Request, status

from src.core.config import settings
from src.core.redis_client import get_redis, mark_unavailable

# Per-process fallback counters (key -> (count, expires_at)), used only while Redis is unavailable.
_memory_counts: dict[str, tuple[int, float]] = {}
_memory_lock = threading.Lock()


def _now() -> float:
    return time.time()


def client_ip(request: Request) -> str:
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # The proxy appends the address it saw; earlier entries are client-controlled.
            return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


class RateLimit:
    """FastAPI dependency allowing `limit` requests per client IP per `window_seconds`.

    Usage: `dependencies=[Depends(RateLimit("login", limit=10, window_seconds=60))]`.
    Fixed windows counted in Redis (shared across processes), falling back to
    in-process counters when Redis is down so limits still apply.
    """

    def __init__(self, name: str, limit: int, window_seconds: int) -> None:
        self.name = name
        self.limit = limit
        self.window_seconds = window_seconds

    def __call__(self, request: Request) -> None:
        if not settings.rate_limit_enabled:
            return
        now = int(_now())
        window = now // self.window_seconds
        key = f"ratelimit:{self.name}:{client_ip(request)}:{window}"
        if self._hit(key) > self.limit:
            retry_after = self.window_seconds - (now % self.window_seconds)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again later.",
                headers={"Retry-After": str(retry_after)},
            )

    def _hit(self, key: str) -> int:
        client = get_redis()
        if client is not None:
            try:
                pipe = client.pipeline()
                pipe.incr(key)
                pipe.expire(key, self.window_seconds)
                count, _ = pipe.execute()
                return int(count)
            except Exception as exc:
                mark_unavailable(exc)
        return self._hit_memory(key)

    def _hit_memory(self, key: str) -> int:
        now = time.monotonic()
        with _memory_lock:
            # Drop expired counters so memory stays bounded.
            for stale in [k for k, (_, expires) in _memory_counts.items() if expires <= now]:
                del _memory_counts[stale]
            count, expires = _memory_counts.get(key, (0, now + self.window_seconds))
            _memory_counts[key] = (count + 1, expires)
            return count + 1
