"""Voice module — minimal security helpers (admin gate + rate limiting).

Trimmed from the original AI-Phone-Agent security.py: everything Twilio-
specific (webhook signature validation, stream tokens) was dropped since
this integration is browser voice chat only.
"""

from __future__ import annotations

import asyncio
import hmac
import os
import time
from collections import defaultdict, deque
from typing import Callable

from fastapi import Header, HTTPException, Request


async def require_admin(x_api_key: str = Header(default="", alias="X-API-Key")) -> None:
    """Protect management APIs. Open by default in dev when ADMIN_API_KEY is unset,
    matching the rest of this platform's current (no-auth) posture — set
    ADMIN_API_KEY in .env to require it."""
    expected = os.getenv("ADMIN_API_KEY", "")
    if not expected:
        return
    if not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid administrator credentials")


class RateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, key: str, limit: int, window_seconds: int = 60) -> None:
        now = time.monotonic()
        cutoff = now - window_seconds
        async with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                raise HTTPException(status_code=429, detail="Too many requests")
            events.append(now)


rate_limiter = RateLimiter()


def rate_limit(bucket: str, limit: int, window_seconds: int = 60) -> Callable:
    async def dependency(request: Request) -> None:
        client = request.client.host if request.client else "unknown"
        await rate_limiter.check(f"{bucket}:{client}", limit, window_seconds)

    return dependency
