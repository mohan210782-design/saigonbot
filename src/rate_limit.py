"""
Simple in-memory rate limiting for FastAPI

Configured via environment variables:
- RATE_LIMIT_ENABLED=true/false
- RATE_LIMIT_WINDOW_SECONDS=60
- RATE_LIMIT_MAX_REQUESTS=60
"""
import os
import time
from typing import Dict, Tuple

from dotenv import load_dotenv

load_dotenv()


RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "false").lower() == "true"
WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
MAX_REQUESTS = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "60"))


class RateLimiter:
    """
    Very simple fixed-window rate limiter.
    Tracks counts per key (e.g., client IP or session_id).
    Not clustered; suitable for a single-instance deployment.
    """

    def __init__(self, window_seconds: int, max_requests: int):
        self.window_seconds = max(window_seconds, 1)
        self.max_requests = max(max_requests, 1)
        # key -> (window_start_timestamp, count)
        self._buckets: Dict[str, Tuple[float, int]] = {}

    def check(self, key: str) -> bool:
        """
        Returns True if request is allowed, False if rate limit exceeded.
        """
        now = time.time()
        bucket = self._buckets.get(key)

        if not bucket:
            # First request for this key
            self._buckets[key] = (now, 1)
            return True

        window_start, count = bucket

        if now - window_start > self.window_seconds:
            # Window has passed, reset
            self._buckets[key] = (now, 1)
            return True

        # Within current window
        if count >= self.max_requests:
            # Exceeded
            return False

        # Increment count
        self._buckets[key] = (window_start, count + 1)
        return True


def get_rate_limiter() -> RateLimiter:
    """
    Global rate limiter instance.
    """
    # Lazy init
    global _rate_limiter
    try:
        _rate_limiter
    except NameError:
        _rate_limiter = RateLimiter(WINDOW_SECONDS, MAX_REQUESTS)
    return _rate_limiter

