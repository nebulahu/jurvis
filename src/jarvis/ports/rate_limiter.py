"""Rate limiter port for API call throttling."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Protocol


class RateLimiter(Protocol):
    """Port for rate limiting API calls."""

    def acquire(self) -> bool:
        """Try to acquire a rate limit token. Returns True if allowed."""
        ...

    def wait(self) -> None:
        """Block until a rate limit token is available."""
        ...


@dataclass
class TokenBucketRateLimiter:
    """Token bucket rate limiter implementation.

    Allows bursts up to max_tokens, then refills at refill_rate per second.
    """

    max_tokens: float
    refill_rate: float  # tokens per second
    _tokens: float = field(init=False, repr=False)
    _last_refill: float = field(init=False, repr=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self._tokens = self.max_tokens
        self._last_refill = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.max_tokens, self._tokens + elapsed * self.refill_rate)
        self._last_refill = now

    def acquire(self) -> bool:
        with self._lock:
            self._refill()
            if self._tokens >= 1:
                self._tokens -= 1
                return True
            return False

    def wait(self) -> None:
        while not self.acquire():
            time.sleep(0.1)


def create_rate_limiter(
    requests_per_minute: int = 60,
    burst_size: int = 10,
) -> RateLimiter:
    """Create a rate limiter with the given parameters."""
    return TokenBucketRateLimiter(
        max_tokens=float(burst_size),
        refill_rate=requests_per_minute / 60.0,
    )
