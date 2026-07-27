"""Exponential backoff with full jitter.

Full jitter (a uniform draw over `[0, capped_delay]`) rather than plain doubling:
when a dependency comes back after an outage, every reconnecting client would
otherwise retry in lockstep and knock it straight back over.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True, slots=True)
class BackoffPolicy:
    initial_seconds: float = 1.0
    max_seconds: float = 60.0
    multiplier: float = 2.0
    jitter: bool = True

    @classmethod
    def from_settings(cls) -> BackoffPolicy:
        return cls(
            initial_seconds=settings.SCANNER_BACKOFF_INITIAL_SECONDS,
            max_seconds=settings.SCANNER_BACKOFF_MAX_SECONDS,
            multiplier=settings.SCANNER_BACKOFF_MULTIPLIER,
        )

    def delay_for(self, attempt: int) -> float:
        """Delay before retry number `attempt` (1-based)."""
        if attempt < 1:
            raise ValueError("attempt must be >= 1")

        raw = self.initial_seconds * (self.multiplier ** (attempt - 1))
        capped = min(raw, self.max_seconds)
        if not self.jitter:
            return capped
        # nosec B311 — jitter needs to be uniform, not cryptographically secure.
        return random.uniform(0.0, capped)  # noqa: S311
