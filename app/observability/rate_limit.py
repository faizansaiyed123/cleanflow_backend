"""
In-process token-bucket rate limiter.

Why token bucket over a fixed window: a fixed window (e.g. "100 req per
minute") allows a burst of 2x the limit right at the window boundary
(100 requests at 0:59, another 100 at 1:00). Token bucket smooths this
out -- tokens refill continuously at a fixed rate, so the maximum burst
is always bounded by the bucket size, never by request timing luck.

Why in-memory rather than Redis: this app has no external dependency
requirement, and a single-process deployment (as this demo runs) has no
need for a shared limiter store. In a multi-instance deployment this
class's interface (`allow(key) -> bool`) is exactly what you'd swap for
a Redis-backed token bucket (e.g. via a Lua script for atomicity)
without touching any call site -- the limiter is injected as a
dependency, not hardcoded into the routes that use it.
"""
import time
import threading
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    last_refill: float


class TokenBucketLimiter:
    def __init__(self, capacity: int, refill_per_second: float):
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> tuple[bool, float]:
        """Returns (allowed, retry_after_seconds)."""
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=self.capacity - 1, last_refill=now)
                self._buckets[key] = bucket
                return True, 0.0

            elapsed = now - bucket.last_refill
            bucket.tokens = min(self.capacity, bucket.tokens + elapsed * self.refill_per_second)
            bucket.last_refill = now

            if bucket.tokens >= 1:
                bucket.tokens -= 1
                return True, 0.0

            deficit = 1 - bucket.tokens
            retry_after = deficit / self.refill_per_second
            return False, retry_after

    def reset(self):
        """Test helper: clear all buckets between test cases."""
        with self._lock:
            self._buckets.clear()


# Two named limiters with different tuning for different abuse profiles:
# login is brute-force-sensitive (tight), public quote requests are
# spam-sensitive (looser, since real customers legitimately hit it once).
login_limiter = TokenBucketLimiter(capacity=5, refill_per_second=5 / 60)       # 5 attempts / minute
public_quote_limiter = TokenBucketLimiter(capacity=10, refill_per_second=10 / 3600)  # 10 / hour
