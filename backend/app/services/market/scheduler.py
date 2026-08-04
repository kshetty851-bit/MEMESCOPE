"""Adaptive refresh scheduling.

A token's information value decays sharply with age. The first half hour decides
whether a meme coin is anything at all, so it is polled every 30 seconds; a
week-old token changes slowly and is polled every few hours. Without tiering,
old tokens would consume the entire provider budget within days simply by
outnumbering new ones.

Pure functions over a frozen policy — no clock, no database — so every tier
boundary and backoff path is unit-testable.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.backoff import BackoffPolicy
from app.core.config import settings


class RefreshTier(enum.StrEnum):
    FRESH = "fresh"
    YOUNG = "young"
    MATURE = "mature"
    OLD = "old"
    #: Not an age band. A token the product is actively displaying — a visible
    #: Radar rank, an open opportunity, a paper position — refreshed on the
    #: cadence the screen implies rather than on the cadence its age implies.
    #: A six-day-old token at Radar rank 3 is OLD by age and PRIORITY by use.
    PRIORITY = "priority"


@dataclass(frozen=True, slots=True)
class SchedulePolicy:
    """Age thresholds (minutes) mapped to refresh intervals (seconds)."""

    fresh_max_minutes: int = 30
    fresh_interval_seconds: int = 30
    young_max_minutes: int = 360
    young_interval_seconds: int = 300
    mature_max_minutes: int = 1440
    mature_interval_seconds: int = 1800
    old_interval_seconds: int = 21600
    #: What a displayed token gets, regardless of age. Published because it is
    #: the promise the freshness indicator is measured against.
    priority_interval_seconds: int = 15

    @classmethod
    def from_settings(cls) -> SchedulePolicy:
        return cls(
            fresh_max_minutes=settings.ENRICHMENT_TIER_FRESH_MAX_MINUTES,
            fresh_interval_seconds=settings.ENRICHMENT_TIER_FRESH_INTERVAL_SECONDS,
            young_max_minutes=settings.ENRICHMENT_TIER_YOUNG_MAX_MINUTES,
            young_interval_seconds=settings.ENRICHMENT_TIER_YOUNG_INTERVAL_SECONDS,
            mature_max_minutes=settings.ENRICHMENT_TIER_MATURE_MAX_MINUTES,
            mature_interval_seconds=settings.ENRICHMENT_TIER_MATURE_INTERVAL_SECONDS,
            old_interval_seconds=settings.ENRICHMENT_TIER_OLD_INTERVAL_SECONDS,
            priority_interval_seconds=settings.ENRICHMENT_PRIORITY_INTERVAL_SECONDS,
        )

    def tier_for_age(self, age_minutes: float) -> RefreshTier:
        if age_minutes < self.fresh_max_minutes:
            return RefreshTier.FRESH
        if age_minutes < self.young_max_minutes:
            return RefreshTier.YOUNG
        if age_minutes < self.mature_max_minutes:
            return RefreshTier.MATURE
        return RefreshTier.OLD

    def interval_for_tier(self, tier: RefreshTier) -> int:
        return {
            RefreshTier.PRIORITY: self.priority_interval_seconds,
            RefreshTier.FRESH: self.fresh_interval_seconds,
            RefreshTier.YOUNG: self.young_interval_seconds,
            RefreshTier.MATURE: self.mature_interval_seconds,
            RefreshTier.OLD: self.old_interval_seconds,
        }[tier]


@dataclass(frozen=True, slots=True)
class ScheduleDecision:
    tier: RefreshTier
    interval_seconds: float
    next_refresh_at: datetime
    reason: str


class RefreshScheduler:
    """Decides when a token should next be refreshed."""

    def __init__(
        self, policy: SchedulePolicy | None = None, backoff: BackoffPolicy | None = None
    ) -> None:
        self.policy = policy or SchedulePolicy.from_settings()
        # Failure backoff is capped at the OLD interval: a token that keeps
        # failing should never be retried more often than a healthy stale one.
        self._backoff = backoff or BackoffPolicy(
            initial_seconds=float(self.policy.fresh_interval_seconds),
            max_seconds=float(self.policy.old_interval_seconds),
            multiplier=2.0,
            jitter=True,
        )

    def decide(
        self,
        *,
        now: datetime,
        discovered_at: datetime,
        consecutive_failures: int = 0,
        consecutive_empty: int = 0,
        priority: bool = False,
    ) -> ScheduleDecision:
        """Compute the next refresh time for one token.

        `priority` overrides the age tier but **not** the failure and
        empty-listing paths below. A displayed token that the provider keeps
        erroring on still backs off: hammering a broken endpoint every fifteen
        seconds would spend the whole budget on the one token least able to use
        it, and the freshness indicator will show the staleness honestly rather
        than the scheduler hiding it.
        """
        age_minutes = max(0.0, (now - discovered_at).total_seconds() / 60.0)
        tier = RefreshTier.PRIORITY if priority else self.policy.tier_for_age(age_minutes)
        base_interval = float(self.policy.interval_for_tier(tier))

        if consecutive_failures > 0:
            # Provider errors: back off exponentially so a broken token stops
            # consuming budget, but never below the tier's own cadence.
            interval = max(base_interval, self._backoff.delay_for(consecutive_failures))
            reason = f"failure_backoff(attempt={consecutive_failures})"
        elif consecutive_empty > 0:
            # No pool indexed yet. Expected for new mints, so ease off gently
            # and linearly rather than punishing them like an error.
            interval = min(
                base_interval * (1 + consecutive_empty),
                float(self.policy.mature_interval_seconds),
            )
            reason = f"awaiting_listing(empty={consecutive_empty})"
        else:
            interval = base_interval
            reason = f"tier({tier})"

        return ScheduleDecision(
            tier=tier,
            interval_seconds=interval,
            next_refresh_at=now + timedelta(seconds=interval),
            reason=reason,
        )

    def should_dead_letter(self, consecutive_failures: int) -> bool:
        return consecutive_failures >= settings.ENRICHMENT_DEAD_LETTER_THRESHOLD
