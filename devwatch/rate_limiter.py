import time
from collections import defaultdict
from typing import Dict, List
from fastapi import HTTPException
from devwatch.config import Config
from devwatch.audit_log import log_rate_limit_exceeded


class SlidingWindowRateLimiter:
    """Sliding-window rate limiter tracking requests per identity or IP address."""

    def __init__(self):
        self.requests: Dict[str, List[float]] = defaultdict(list)

    def check_rate_limit(self, key: str, max_requests: int, window_seconds: int = 60, endpoint: str = "API") -> None:
        now = time.time()
        window_start = now - window_seconds

        # Prune timestamps outside window
        self.requests[key] = [t for t in self.requests[key] if t > window_start]

        if len(self.requests[key]) >= max_requests:
            log_rate_limit_exceeded(endpoint, key)
            retry_after = int(window_seconds - (now - self.requests[key][0]))
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Maximum {max_requests} requests per {window_seconds}s allowed. Try again in {retry_after}s.",
                headers={"Retry-After": str(max(1, retry_after))},
            )

        self.requests[key].append(now)

    def reset(self) -> None:
        """Reset all rate limiter tracking state (useful for tests)."""
        self.requests.clear()


rate_limiter = SlidingWindowRateLimiter()
