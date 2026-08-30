"""Rate limiting and retry policy for the Polygon API.

Polygon throttles clients that issue requests too quickly, and rbx uploads are
bursty by nature: :mod:`rbx.box.packaging.polygon.upload` pushes files, tests
and solutions from a pool of worker threads. When the throttle kicks in Polygon
answers with an HTTP 429/5xx, an HTML error page instead of JSON, or a regular
JSON body with ``status: FAILED`` and a "too many requests" comment -- none of
which used to be retried, so a whole upload died on a transient hiccup.

This module centralizes two complementary defenses, both applied by
``Request`` in :mod:`rbx.box.packaging.polygon.polygon_api`:

- a process-wide :class:`RateLimiter` that spaces out request *starts* across
  every thread, and widens that spacing on its own whenever Polygon complains;
- :func:`backoff_delay`, the exponential-with-jitter schedule used to wait
  between retries of a single request.

Both are tunable through the environment, for the rare package that needs to be
gentler (or more aggressive) than the defaults:

``RBX_POLYGON_MIN_INTERVAL``
    Seconds between consecutive request starts (default ``0.25``).
``RBX_POLYGON_MAX_INTERVAL``
    Upper bound the adaptive spacing may grow to (default ``5.0``).
``RBX_POLYGON_MAX_RETRIES``
    Retries after the first attempt (default ``6``, i.e. 7 attempts).
"""

import os
import random
import re
import threading
import time
from typing import Optional

# Polygon phrases that mean "you are going too fast, come back later" rather
# than "your request is wrong". Matched against the ``comment`` of a FAILED
# response, case-insensitively.
_RETRYABLE_COMMENT_RE = re.compile(
    r'too many requests'
    r'|rate.?limit'
    r'|try again later'
    r'|temporarily unavailable'
    r'|service unavailable'
    r'|internal server error'
    r'|please,? wait',
    re.IGNORECASE,
)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, '') or default)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, '') or default)
    except ValueError:
        return default


def max_retries() -> int:
    return max(0, _env_int('RBX_POLYGON_MAX_RETRIES', 6))


def request_timeout() -> float:
    """Per-request socket timeout, in seconds."""
    return _env_float('RBX_POLYGON_TIMEOUT', 120.0)


def is_retryable_comment(comment: Optional[str]) -> bool:
    """Whether a FAILED response's comment describes a transient condition."""
    return bool(comment) and _RETRYABLE_COMMENT_RE.search(comment or '') is not None


def is_retryable_status(status_code: int) -> bool:
    """Whether an HTTP status code is worth retrying."""
    return status_code == 429 or status_code == 408 or status_code >= 500


def backoff_delay(attempt: int, retry_after: Optional[float] = None) -> float:
    """Seconds to wait before retry number ``attempt`` (0-based).

    Exponential from a 1s base, capped at 30s, with full-width jitter so that
    concurrent workers do not synchronize their retries into a new burst. A
    server-provided ``Retry-After`` always wins, since it is the only figure
    Polygon actually promises.
    """
    if retry_after is not None and retry_after > 0:
        return min(retry_after, 120.0)
    base = min(30.0, 2.0**attempt)
    return base * random.uniform(0.5, 1.5)


def parse_retry_after(value: Optional[str]) -> Optional[float]:
    """Parse a ``Retry-After`` header expressed in seconds."""
    if not value:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    return seconds if seconds > 0 else None


class RateLimiter:
    """Spaces out request starts, and backs off when Polygon pushes back.

    The limiter is shared by every thread in the process, so the spacing holds
    across the worker pools in ``upload.py``. It starts optimistic (a short
    interval) and only slows down after Polygon actually throttles us, doubling
    the interval on each complaint up to ``max_interval`` and decaying back
    towards the floor after a streak of clean responses -- so a package that
    trips the throttle once does not pay for it until the end of the upload.
    """

    _DECAY_AFTER_SUCCESSES = 10

    def __init__(
        self,
        min_interval: Optional[float] = None,
        max_interval: Optional[float] = None,
    ):
        self._floor = (
            min_interval
            if min_interval is not None
            else _env_float('RBX_POLYGON_MIN_INTERVAL', 0.25)
        )
        self._ceiling = (
            max_interval
            if max_interval is not None
            else _env_float('RBX_POLYGON_MAX_INTERVAL', 5.0)
        )
        self._ceiling = max(self._ceiling, self._floor)
        self._interval = self._floor
        self._next_at = 0.0
        self._successes = 0
        self._lock = threading.Lock()

    @property
    def interval(self) -> float:
        return self._interval

    def acquire(self) -> None:
        """Block until enough time has passed since the previous request."""
        while True:
            with self._lock:
                now = time.monotonic()
                if now >= self._next_at:
                    self._next_at = now + self._interval
                    return
                wait = self._next_at - now
            time.sleep(wait)

    def penalize(self, retry_after: Optional[float] = None) -> None:
        """Widen the spacing after Polygon refused a request.

        Also pushes the next allowed start past the retry delay, so the other
        threads wait alongside the one that got throttled instead of piling
        more requests onto a server that just asked for room.
        """
        with self._lock:
            self._successes = 0
            self._interval = min(self._ceiling, max(self._floor, self._interval * 2))
            quiet_for = max(self._interval, retry_after or 0.0)
            self._next_at = max(self._next_at, time.monotonic() + quiet_for)

    def report_success(self) -> None:
        """Relax the spacing again after a streak of accepted requests."""
        with self._lock:
            if self._interval <= self._floor:
                return
            self._successes += 1
            if self._successes >= self._DECAY_AFTER_SUCCESSES:
                self._successes = 0
                self._interval = max(self._floor, self._interval / 2)


_limiter: Optional[RateLimiter] = None
_limiter_lock = threading.Lock()


def get_limiter() -> RateLimiter:
    """The process-wide limiter shared by every Polygon request."""
    global _limiter
    with _limiter_lock:
        if _limiter is None:
            _limiter = RateLimiter()
        return _limiter


def reset_limiter() -> None:
    """Drop the shared limiter (used by tests)."""
    global _limiter
    with _limiter_lock:
        _limiter = None
