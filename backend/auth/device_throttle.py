"""
Throttle devices that keep presenting a rejected device token.

ncclient before v0.7.0 retried a rejected token in a tight loop (no delay) when it
ran as a service, so a revoked, deleted or re-enrolled device could send hundreds of
requests a second. Once the same rejected token has been seen LIMIT times within
WINDOW seconds, further requests with it get 429 + Retry-After instead of 401
(without touching the database). Old clients treat any non-401 failure as "wait one
poll interval", which breaks the loop; current clients never resend a token after a
401 anyway, so they always see the 401.

In-memory and per process: it only has to take the edge off a misbehaving client,
not survive restarts. Tokens are keyed by their SHA-256, never stored as-is.
"""
from __future__ import annotations

import hashlib
import math
import threading
import time
from typing import Callable

LIMIT = 3
WINDOW_SECONDS = 60.0
MAX_ENTRIES = 10_000


class RejectedTokenThrottle:
    def __init__(
        self,
        limit: int = LIMIT,
        window: float = WINDOW_SECONDS,
        max_entries: int = MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window
        self._max_entries = max_entries
        self._clock = clock
        self._lock = threading.Lock()
        # token hash -> (window start, rejections in this window)
        self._seen: dict[str, tuple[float, int]] = {}

    @staticmethod
    def _key(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8", "replace")).hexdigest()

    def retry_after(self, token: str) -> "int | None":
        """Seconds the caller should wait, if this token is being throttled."""
        now = self._clock()
        with self._lock:
            entry = self._seen.get(self._key(token))
            if entry is None:
                return None
            start, count = entry
            remaining = self._window - (now - start)
            if remaining <= 0 or count < self._limit:
                return None
            return max(1, math.ceil(remaining))

    def record_rejection(self, token: str) -> None:
        now = self._clock()
        key = self._key(token)
        with self._lock:
            start, count = self._seen.get(key, (now, 0))
            if now - start >= self._window:
                start, count = now, 0
            self._seen[key] = (start, count + 1)
            if len(self._seen) > self._max_entries:
                self._prune(now)

    def _prune(self, now: float) -> None:
        for key in [k for k, (start, _) in self._seen.items() if now - start >= self._window]:
            del self._seen[key]
        # Still over (a flood of distinct tokens): drop the oldest windows.
        if len(self._seen) > self._max_entries:
            oldest = sorted(self._seen, key=lambda k: self._seen[k][0])
            for key in oldest[: len(self._seen) - self._max_entries]:
                del self._seen[key]


rejected_device_tokens = RejectedTokenThrottle()
