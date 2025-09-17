import time
import threading
from collections import deque
from typing import Optional

class RateLimiter:
    """Thread-safe sliding-window limiter with timeout & try_acquire."""
    def __init__(self, max_calls: int, period_sec: float):
        self.max_calls = max_calls
        self.period = period_sec
        self._hits = deque()  # monotonic() timestamps
        self._cv = threading.Condition()

    def _prune(self, now: float):
        while self._hits and (now - self._hits[0]) > self.period:
            self._hits.popleft()

    def try_acquire(self) -> bool:
        """Return immediately; True if a slot was acquired."""
        now = time.monotonic()
        with self._cv:
            self._prune(now)
            if len(self._hits) < self.max_calls:
                self._hits.append(now)
                # Wake any waiters who might now fit (rare, but harmless)
                self._cv.notify_all()
                return True
            return False

    def wait(self, timeout: Optional[float] = None) -> bool:
        """
        Block until a slot is available or timeout expires.
        Returns True if acquired, False if timed out.
        """
        deadline = None if timeout is None else (time.monotonic() + timeout)
        with self._cv:
            while True:
                now = time.monotonic()
                self._prune(now)

                if len(self._hits) < self.max_calls:
                    self._hits.append(now)
                    self._cv.notify_all()
                    return True

                # Compute how long until the oldest hit falls out of the window
                sleep_for = self.period - (now - self._hits[0])
                if sleep_for < 0:
                    sleep_for = 0

                if deadline is not None:
                    remaining = deadline - now
                    if remaining <= 0:
                        return False
                    sleep_for = min(sleep_for, remaining)

                self._cv.wait(timeout=sleep_for)
