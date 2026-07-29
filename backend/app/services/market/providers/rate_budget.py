"""A non-blocking call budget for secondary providers.

A token bucket, with one deliberate difference from the usual implementation:
`try_acquire()` never waits. It returns False and the caller moves on.

That is the whole point. This budget guards a *supplementary* provider — one
that fills a gap in the primary's data. Blocking the enrichment loop until a
secondary's allowance refills would trade a complete snapshot for a late one,
and snapshots are the durable asset (see MEMESCOPE_MASTER_CONTEXT §4). A missing
liquidity figure is a known, reported gap; a snapshot that arrives two minutes
after the observation it describes is silently wrong data.

Time is injected rather than read, so tests are deterministic and do not sleep.
"""

from __future__ import annotations

import time
from collections.abc import Callable


class CallBudget:
    """Allows at most `capacity` acquisitions per `window_seconds`.

    Refills continuously rather than in steps: a fixed-window counter would let
    a caller spend the whole allowance in the last instant of one window and
    again in the first instant of the next, producing a burst of twice the
    intended rate against a vendor that rate-limits on a sliding window.
    """

    __slots__ = ("_capacity", "_clock", "_denied", "_tokens", "_updated_at", "_window")

    def __init__(
        self,
        capacity: int,
        window_seconds: float = 60.0,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if capacity < 0:
            raise ValueError("capacity must not be negative")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")

        self._capacity = capacity
        self._window = window_seconds
        # Start full: a freshly started worker has spent nothing.
        self._tokens = float(capacity)
        self._clock = clock or time.monotonic
        self._updated_at = self._clock()
        self._denied = 0

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def denied(self) -> int:
        """How many acquisitions have been refused since construction.

        Exposed so the worker can report the size of the gap it left rather
        than leaving budget exhaustion invisible.
        """
        return self._denied

    def _refill(self) -> None:
        now = self._clock()
        elapsed = now - self._updated_at
        if elapsed <= 0:
            # A non-monotonic or stalled clock must not mint tokens.
            self._updated_at = now
            return
        self._tokens = min(
            float(self._capacity), self._tokens + elapsed * (self._capacity / self._window)
        )
        self._updated_at = now

    def available(self) -> int:
        self._refill()
        return int(self._tokens)

    def try_acquire(self, count: int = 1) -> bool:
        """Spend `count` from the budget if it is there. Never blocks."""
        if count <= 0:
            return True
        self._refill()
        if self._tokens >= count:
            self._tokens -= count
            return True
        self._denied += 1
        return False
