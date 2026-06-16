from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Deque

from fastapi import HTTPException, Request, status


_buckets: dict[str, Deque[float]] = defaultdict(deque)


def rate_limit(scope: str, *, limit: int, window_seconds: int):
    async def _dependency(request: Request) -> None:
        now = time.monotonic()
        forwarded_for = str(request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        client_host = request.client.host if request.client else "unknown"
        key = f"{scope}:{forwarded_for or client_host}"
        bucket = _buckets[key]

        while bucket and now - bucket[0] > window_seconds:
            bucket.popleft()

        if len(bucket) >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again later.",
            )

        bucket.append(now)

    return _dependency
