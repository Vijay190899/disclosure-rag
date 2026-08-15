"""API keys and rate limiting.

Both are off unless configured, and that default is deliberate rather than lazy.
The service is run locally against a mounted corpus far more often than it is
exposed, and a demo that refuses to answer until you invent a credential is a
demo nobody runs. Turning either on is one environment variable.

The important half is what happens when they *are* configured: no key means no
answer, comparison is constant time, and the key never reaches a log line.
"""

from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException, Request, status

HEADER = "x-api-key"

# Open endpoints. Liveness has to answer before a key is checked, or a load
# balancer cannot tell "unauthenticated" from "down", and metrics scraping is an
# internal concern that would otherwise need its own credential.
OPEN_PATHS = frozenset({"/health", "/metrics", "/openapi.json", "/docs", "/redoc"})


class ApiKeys:
    """The configured keys, compared without leaking timing.

    ``hmac.compare_digest`` rather than ``==``: string comparison returns early
    on the first differing byte, which leaks the length of the shared prefix.
    That is a small leak and it is free to close.
    """

    def __init__(self, keys: str) -> None:
        self.keys = tuple(key.strip() for key in keys.split(",") if key.strip())

    @property
    def enabled(self) -> bool:
        return bool(self.keys)

    def accepts(self, presented: str | None) -> bool:
        if not self.enabled:
            return True
        if not presented:
            return False
        return any(hmac.compare_digest(presented, key) for key in self.keys)


class RateLimiter:
    """A fixed number of requests per client per window.

    A sliding window over timestamps, in memory. Honest about what that means:
    the counter is per process, so two replicas allow twice the rate, and it
    resets on restart. For a single container in front of a read-only corpus
    that is the right amount of machinery. A shared limiter belongs in the
    ingress once there is an ingress.
    """

    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window = window_seconds
        self._seen: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    @property
    def enabled(self) -> bool:
        return self.limit > 0

    def check(self, client: str, now: float | None = None) -> int:
        """Record a request and return how many remain. Raises when over."""
        if not self.enabled:
            return self.limit
        moment = time.monotonic() if now is None else now
        with self._lock:
            hits = self._seen[client]
            while hits and moment - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"rate limit is {self.limit} requests per {self.window:.0f}s",
                    headers={"retry-after": str(int(self.window - (moment - hits[0])) + 1)},
                )
            hits.append(moment)
            return self.limit - len(hits)


def client_of(request: Request) -> str:
    """Who to count against.

    The API key when there is one, since that identifies the caller better than
    an address behind a proxy. Otherwise the peer address. Deliberately not
    ``x-forwarded-for``: that header is caller-controlled, so trusting it
    unconditionally turns the limiter off for anyone who reads this file.
    """
    presented = request.headers.get(HEADER)
    if presented:
        return f"key:{presented[:8]}"
    return f"ip:{request.client.host if request.client else 'unknown'}"


def enforce(request: Request, keys: ApiKeys, limiter: RateLimiter) -> None:
    """Reject unauthenticated or over-rate requests before any work happens."""
    if request.url.path in OPEN_PATHS:
        return
    if not keys.accepts(request.headers.get(HEADER)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"missing or invalid {HEADER}",
            headers={"www-authenticate": HEADER},
        )
    limiter.check(client_of(request))
