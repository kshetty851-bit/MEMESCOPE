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
    #: The fresh-token nursery lane. Same age band as FRESH, but claimed ahead
    #: of the backlog: the FRESH tier's 30-second interval was meaningless when
    #: a due fresh token sorted behind 238,000 overdue rows and waited hours
    #: for a claim that its whole information value had already decayed past.
    NURSERY = "nursery"


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
    #: The nursery cadence. Deliberately slower than the display lane's 15s and
    #: the FRESH tier's nominal 30s: the lane holds up to
    #: `ENRICHMENT_NURSERY_MAX_TOKENS` tokens and its worst-case claim demand is
    #: `cap * 60 / interval` per minute, which must fit inside the worker's
    #: measured throughput (~1,000 claims/min) *after* the display lane is fed.
    nursery_interval_seconds: int = 60
    #: How long a nursery-lane token keeps the nursery cadence. Was implicitly
    #: `fresh_max_minutes` (30). The Radar's observation window (V4 Phase 2)
    #: holds a token OBSERVING for `RADAR_MIN_OBSERVATION_MINUTES` before it
    #: may be admitted, and measured on 2026-08-24 those tokens fell to the
    #: YOUNG tier's 5-minute cadence half way through — 4-8 observations where
    #: the window promised ~60. A window that does not observe is not a
    #: window. The anti-staleness intent of the original bound is kept: past
    #: this horizon a lagging membership beat still cannot hold a stale token
    #: on the fast cadence.
    nursery_window_minutes: int = 30

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
            nursery_window_minutes=max(
                settings.ENRICHMENT_TIER_FRESH_MAX_MINUTES,
                settings.RADAR_MIN_OBSERVATION_MINUTES,
            ),
            nursery_interval_seconds=settings.ENRICHMENT_NURSERY_INTERVAL_SECONDS,
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
            RefreshTier.NURSERY: self.nursery_interval_seconds,
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
        nursery: bool = False,
        ever_had_data: bool = False,
    ) -> ScheduleDecision:
        """Compute the next refresh time for one token.

        `priority` overrides the age tier but **not** the failure and
        empty-listing paths below. A displayed token that the provider keeps
        erroring on still backs off: hammering a broken endpoint every fifteen
        seconds would spend the whole budget on the one token least able to use
        it, and the freshness indicator will show the staleness honestly rather
        than the scheduler hiding it.

        `nursery` is subordinate to `priority` and applies only while the token
        is still inside the FRESH age window — a nursery row the membership beat
        has not yet evicted schedules by its true age, so a lagging beat can
        never keep a stale token on the nursery cadence. Both failure paths
        still apply to it, for the same reason they apply to `priority`.
        """
        age_minutes = max(0.0, (now - discovered_at).total_seconds() / 60.0)
        if priority:
            tier = RefreshTier.PRIORITY
        elif nursery and age_minutes < self.policy.nursery_window_minutes:
            tier = RefreshTier.NURSERY
        else:
            tier = self.policy.tier_for_age(age_minutes)
        base_interval = float(self.policy.interval_for_tier(tier))

        if consecutive_failures > 0:
            # Provider errors: back off exponentially so a broken token stops
            # consuming budget, but never below the tier's own cadence.
            interval = max(base_interval, self._backoff.delay_for(consecutive_failures))
            reason = f"failure_backoff(attempt={consecutive_failures})"
        elif consecutive_empty > 0 and not ever_had_data:
            # No pool indexed YET. Expected for new mints, so ease off gently
            # and linearly rather than punishing them like an error.
            interval = min(
                base_interval * (1 + consecutive_empty),
                float(self.policy.mature_interval_seconds),
            )
            reason = f"awaiting_listing(empty={consecutive_empty})"
        elif consecutive_empty > 0:
            # HAD a pool and lost it. That is a death, not a token waiting to
            # be listed, and the two must not share a backoff.
            #
            # Easing off here is how the platform stopped watching tokens at
            # the exact moment they were failing. It is also self-reinforcing:
            # each empty result lengthens the interval, so the next empty
            # arrives later, so the death is timestamped later still. Measured
            # 2026-09-04, the effect was large enough to bias market-wide
            # return estimates from -2.3% to +16.4% — the difference between a
            # losing population and an apparently profitable one, produced
            # entirely by watching the losers less.
            #
            # So a dying token is polled at the FASTER of its own tier and the
            # mature cadence, and never backs off.
            #
            # `min`, not the tier alone: an OLD token sits on a six-hour tier,
            # and the previous code accidentally sped it up, because the empty
            # backoff was capped at the mature interval which is shorter. That
            # accident was the only thing giving old tokens a usable death
            # time, and holding the tier here would have removed it — a fix
            # that made the very tokens this is for less observable, not more.
            #
            # So: never slower than mature, never slower than the tier already
            # was, no growth with the empty count.
            interval = min(base_interval, float(self.policy.mature_interval_seconds))
            reason = f"confirming_death(empty={consecutive_empty})"
        else:
            interval = base_interval
            reason = f"tier({tier})"

        return ScheduleDecision(
            tier=tier,
            interval_seconds=interval,
            next_refresh_at=now + timedelta(seconds=interval),
            reason=reason,
        )

    def should_dead_letter(
        self,
        consecutive_failures: int,
        *,
        now: datetime | None = None,
        failing_since: datetime | None = None,
    ) -> bool:
        """Whether a token has failed enough, for long enough, to be parked.

        A count alone is the wrong test, and the incident of 2026-08-05 is why.
        The threshold is ten failures; the priority lane re-claims every fifteen
        seconds and the normal lane every couple of minutes, so the same ten
        failures mean two and a half minutes of trouble in one lane and twenty
        in the other. **The tokens the product most wants fresh were therefore
        the most fragile**, which is exactly backwards.

        So elapsed time is now a second, independent condition: a token is only
        dead-lettered once it has been failing for at least
        `ENRICHMENT_DEAD_LETTER_MIN_MINUTES` as well. A brief outage can no
        longer park anything, whatever cadence it happens to hit.

        `failing_since` is the token's last success, or `None` if it has never
        had one — in which case only the count applies, since there is no
        healthy moment to measure from and the token has never worked at all.
        """
        if consecutive_failures < settings.ENRICHMENT_DEAD_LETTER_THRESHOLD:
            return False
        if now is None or failing_since is None:
            return True
        minimum = timedelta(minutes=settings.ENRICHMENT_DEAD_LETTER_MIN_MINUTES)
        return now - failing_since >= minimum
