import time, random
from typing import Callable, Iterable, Optional, Type, Tuple

def with_backoff(
    fn: Callable,
    *,
    attempts: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter_ratio: float = 0.1,
    retry_on: Tuple[Type[BaseException], ...] = (Exception,),
    should_retry: Optional[Callable[[BaseException], bool]] = None,
    on_retry: Optional[Callable[[int, BaseException, float], None]] = None,
):
    """
    Exponential backoff with jitter.
    - retry_on: which exception types to retry
    - should_retry: optional predicate for finer control (e.g. only 429/5xx)
    - on_retry: callback (attempt_idx, exc, sleep_seconds)
    """
    last_exc = None
    for i in range(attempts):
        try:
            return fn()
        except retry_on as e:
            if should_retry and not should_retry(e):
                raise
            last_exc = e
            if i == attempts - 1:
                break
            sleep = min(max_delay, base_delay * (2 ** i))
            # jitter ~ up to ±jitter_ratio
            sleep *= (1.0 + random.uniform(-jitter_ratio, jitter_ratio))
            if on_retry:
                on_retry(i + 1, e, sleep)
            time.sleep(max(0.0, sleep))
    assert last_exc is not None
    raise last_exc
