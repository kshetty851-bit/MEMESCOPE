"""Unit tests for adaptive refresh scheduling."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest

from app.core.backoff import BackoffPolicy
from app.services.market.scheduler import RefreshScheduler, RefreshTier, SchedulePolicy

pytestmark = pytest.mark.unit

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)

POLICY = SchedulePolicy(
    fresh_max_minutes=30,
    fresh_interval_seconds=30,
    young_max_minutes=360,
    young_interval_seconds=300,
    mature_max_minutes=1440,
    mature_interval_seconds=1800,
    old_interval_seconds=21600,
)

# Deterministic backoff so failure paths assert exact numbers.
NO_JITTER = BackoffPolicy(
    initial_seconds=30.0, max_seconds=21600.0, multiplier=2.0, jitter=False
)


def _scheduler() -> RefreshScheduler:
    return RefreshScheduler(policy=POLICY, backoff=NO_JITTER)


@pytest.mark.parametrize(
    ("age_minutes", "expected"),
    [
        (0, RefreshTier.FRESH),
        (29.9, RefreshTier.FRESH),
        (30, RefreshTier.YOUNG),
        (359, RefreshTier.YOUNG),
        (360, RefreshTier.MATURE),
        (1439, RefreshTier.MATURE),
        (1440, RefreshTier.OLD),
        (100_000, RefreshTier.OLD),
    ],
)
def test_tier_boundaries(age_minutes: float, expected: RefreshTier) -> None:
    assert POLICY.tier_for_age(age_minutes) is expected


@pytest.mark.parametrize(
    ("age_minutes", "expected_seconds"),
    [(5, 30), (60, 300), (700, 1800), (5000, 21600)],
)
def test_interval_matches_tier(age_minutes: float, expected_seconds: int) -> None:
    decision = _scheduler().decide(now=NOW, discovered_at=NOW - timedelta(minutes=age_minutes))
    assert decision.interval_seconds == expected_seconds
    assert decision.next_refresh_at == NOW + timedelta(seconds=expected_seconds)


def test_fresh_tokens_refresh_far_more_often_than_old_ones() -> None:
    fresh = _scheduler().decide(now=NOW, discovered_at=NOW - timedelta(minutes=1))
    old = _scheduler().decide(now=NOW, discovered_at=NOW - timedelta(days=7))
    assert old.interval_seconds > fresh.interval_seconds * 100


def test_failures_back_off_exponentially() -> None:
    scheduler = _scheduler()
    delays = [
        scheduler.decide(
            now=NOW,
            discovered_at=NOW - timedelta(minutes=1),
            consecutive_failures=n,
        ).interval_seconds
        for n in (1, 2, 3, 4)
    ]
    assert delays == [30.0, 60.0, 120.0, 240.0]
    assert all(later >= earlier for earlier, later in pairwise(delays))


def test_failure_backoff_never_refreshes_faster_than_the_tier() -> None:
    """A failing old token must not be polled more often than a healthy one."""
    decision = _scheduler().decide(
        now=NOW, discovered_at=NOW - timedelta(days=7), consecutive_failures=1
    )
    assert decision.interval_seconds >= POLICY.old_interval_seconds


def test_empty_results_ease_off_linearly_not_exponentially() -> None:
    """No pool yet is expected for new mints, so it is treated gently."""
    scheduler = _scheduler()
    first = scheduler.decide(
        now=NOW, discovered_at=NOW - timedelta(minutes=1), consecutive_empty=1
    )
    second = scheduler.decide(
        now=NOW, discovered_at=NOW - timedelta(minutes=1), consecutive_empty=3
    )
    assert first.interval_seconds == 60.0
    assert second.interval_seconds == 120.0
    assert "awaiting_listing" in second.reason


def test_empty_backoff_is_capped() -> None:
    decision = _scheduler().decide(
        now=NOW, discovered_at=NOW - timedelta(minutes=1), consecutive_empty=10_000
    )
    assert decision.interval_seconds == POLICY.mature_interval_seconds


def test_failure_takes_precedence_over_empty() -> None:
    decision = _scheduler().decide(
        now=NOW,
        discovered_at=NOW - timedelta(minutes=1),
        consecutive_failures=2,
        consecutive_empty=5,
    )
    assert "failure_backoff" in decision.reason


def test_reason_names_the_tier_on_the_happy_path() -> None:
    decision = _scheduler().decide(now=NOW, discovered_at=NOW - timedelta(minutes=1))
    assert decision.reason == "tier(fresh)"


def test_future_discovery_time_does_not_produce_negative_age() -> None:
    """Clock skew must not crash the scheduler."""
    decision = _scheduler().decide(now=NOW, discovered_at=NOW + timedelta(minutes=5))
    assert decision.tier is RefreshTier.FRESH


def test_policy_reads_from_settings() -> None:
    policy = SchedulePolicy.from_settings()
    assert policy.fresh_interval_seconds > 0
    assert policy.old_interval_seconds > policy.fresh_interval_seconds


class TestDeadLetteringNeedsTimeAsWellAsCount:
    """Why a failure count alone is the wrong test.

    The threshold is ten failures. The priority lane re-claims every fifteen
    seconds and the normal lane every couple of minutes, so the same ten
    failures mean two and a half minutes of trouble in one lane and twenty in
    the other — the tokens the product most wants fresh were the easiest to
    park, which is exactly backwards. On 2026-08-05 that removed 163 of the 200
    priority-lane tokens during a single 60-second provider outage.

    Elapsed failing time is now an independent second condition.
    """

    def test_the_count_alone_no_longer_parks_a_token(self) -> None:
        assert not _scheduler().should_dead_letter(
            50, now=NOW, failing_since=NOW - timedelta(minutes=2)
        )

    def test_a_token_failing_long_enough_is_parked(self) -> None:
        assert _scheduler().should_dead_letter(
            10, now=NOW, failing_since=NOW - timedelta(hours=6)
        )

    def test_time_alone_does_not_park_a_token_either(self) -> None:
        """Both conditions, not either. A token that failed twice a week ago
        and has worked since is not a dead letter."""
        assert not _scheduler().should_dead_letter(
            2, now=NOW, failing_since=NOW - timedelta(days=7)
        )

    def test_a_token_that_never_succeeded_falls_back_to_the_count(self) -> None:
        """There is no healthy moment to measure elapsed failure from, and a
        mint that has never once returned data is a different case from one
        that broke this afternoon."""
        assert _scheduler().should_dead_letter(10, now=NOW, failing_since=None)
