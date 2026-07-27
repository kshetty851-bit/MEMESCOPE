"""Feature construction and windowing.

The tier-interaction sweep is the important part. A fixed feature window
collides with the Day 3 adaptive refresh tiers: at a six-hour refresh interval a
one-hour window holds at most one observation, which would permanently cap
evidence for every healthy token over a day old. These tests assert that a
well-behaved token in *every* tier can reach full depth.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.services.market.scheduler import RefreshTier, SchedulePolicy
from app.services.scoring.features import (
    Observation,
    age_minutes_of,
    build_feature_set,
    default_policy,
    window_seconds_for,
)
from tests.unit.scoring_builders import NOW, features, observations

pytestmark = pytest.mark.unit

POLICY = SchedulePolicy()


@dataclass
class FakeToken:
    mint_address: str = "MintFeature"
    block_time: datetime | None = None
    discovered_at: datetime = NOW
    metadata_status: str = "resolved"


@dataclass
class FakeSnapshot:
    captured_at: datetime
    price_usd: Decimal | None = Decimal("0.001")
    liquidity_usd: Decimal | None = Decimal(50000)
    market_cap: Decimal | None = Decimal(500000)
    fully_diluted_valuation: Decimal | None = Decimal(550000)
    volume_24h: Decimal | None = Decimal(20000)
    volume_1h: Decimal | None = Decimal(2000)
    volume_5m: Decimal | None = Decimal(200)
    buy_count_24h: int | None = 300
    sell_count_24h: int | None = 200
    trading_status: Any = "trading"


# --- Windowing ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("age_minutes", "expected_tier"),
    [
        (1, RefreshTier.FRESH),
        (29, RefreshTier.FRESH),
        (120, RefreshTier.YOUNG),
        (700, RefreshTier.MATURE),
        (5000, RefreshTier.OLD),
    ],
)
def test_tier_comes_from_age_not_from_stored_state(
    age_minutes: int, expected_tier: RefreshTier
) -> None:
    """`TokenEnrichmentState.tier` is null until a token's first refresh."""
    tier, _, _ = window_seconds_for(Decimal(age_minutes), policy=POLICY)
    assert tier == str(expected_tier)


@pytest.mark.parametrize(
    ("age_minutes", "expected_window"),
    [
        (1, 3600),  # fresh: 12 x 30s = 360s, lifted to the 1h floor
        (120, 3600),  # young: 12 x 300s = 3600s
        (700, 21600),  # mature: 12 x 1800s = 6h
        (5000, 259200),  # old: 12 x 21600s = 72h
    ],
)
def test_window_is_tier_relative(age_minutes: int, expected_window: int) -> None:
    _, _, window = window_seconds_for(
        Decimal(age_minutes), policy=POLICY, feature_window=12
    )
    assert window == expected_window


def test_window_respects_the_floor_and_ceiling() -> None:
    _, _, floored = window_seconds_for(
        Decimal(1), policy=POLICY, feature_window=1, minimum_seconds=7200
    )
    assert floored == 7200

    _, _, capped = window_seconds_for(
        Decimal(50000), policy=POLICY, feature_window=1000, maximum_seconds=604800
    )
    assert capped == 604800


@pytest.mark.parametrize("age_minutes", [1, 120, 700, 5000])
def test_every_tier_can_reach_full_depth(age_minutes: int) -> None:
    """The regression this suite exists for.

    A token refreshed at its tier's own cadence must accumulate the full window,
    whatever that cadence is. Under a fixed one-hour window the mature and old
    cases would top out at two observations and one respectively.
    """
    tier, interval, window = window_seconds_for(
        Decimal(age_minutes), policy=POLICY, feature_window=12
    )
    token = FakeToken(block_time=NOW - timedelta(minutes=age_minutes))
    snapshots = [
        FakeSnapshot(captured_at=NOW - timedelta(seconds=interval * index))
        for index in range(12)
    ]

    feature_set = build_feature_set(token, snapshots, now=NOW, policy=POLICY)

    assert feature_set.tier == tier
    assert feature_set.history_window_seconds == window
    assert feature_set.observations == 12


def test_risk_window_never_exceeds_the_history_window() -> None:
    """A fresh token's history is short; the rug window cannot outrun it."""
    token = FakeToken(block_time=NOW - timedelta(minutes=1))
    feature_set = build_feature_set(
        token,
        [FakeSnapshot(captured_at=NOW)],
        now=NOW,
        policy=POLICY,
        risk_window_seconds=999999,
    )
    assert feature_set.risk_window_seconds == feature_set.history_window_seconds


def test_default_policy_is_the_enrichment_scheduler_s() -> None:
    """One source of truth for cadence; duplicating it would guarantee drift."""
    assert default_policy().fresh_interval_seconds == POLICY.fresh_interval_seconds


# --- Age ----------------------------------------------------------------------


def test_age_prefers_on_chain_time() -> None:
    """`discovered_at` is our ingestion latency, not the token's age."""
    token = FakeToken(
        block_time=NOW - timedelta(hours=5), discovered_at=NOW - timedelta(minutes=1)
    )
    assert age_minutes_of(token, now=NOW) == Decimal(300)


def test_age_falls_back_to_discovery() -> None:
    token = FakeToken(block_time=None, discovered_at=NOW - timedelta(minutes=42))
    assert age_minutes_of(token, now=NOW) == Decimal(42)


def test_age_is_never_negative() -> None:
    """A provider clock running ahead must not produce a negative age."""
    token = FakeToken(block_time=NOW + timedelta(hours=1))
    assert age_minutes_of(token, now=NOW) == Decimal(0)


# --- Assembly -----------------------------------------------------------------


def test_snapshots_are_ordered_newest_first_regardless_of_input_order() -> None:
    token = FakeToken(block_time=NOW - timedelta(hours=2))
    shuffled = [
        FakeSnapshot(captured_at=NOW - timedelta(minutes=10)),
        FakeSnapshot(captured_at=NOW),
        FakeSnapshot(captured_at=NOW - timedelta(minutes=5)),
    ]
    feature_set = build_feature_set(token, shuffled, now=NOW, policy=POLICY)

    captured = [entry.captured_at for entry in feature_set.window]
    assert captured == sorted(captured, reverse=True)
    assert feature_set.latest_snapshot_at == NOW


def test_snapshots_outside_the_window_are_dropped() -> None:
    token = FakeToken(block_time=NOW - timedelta(hours=2))
    feature_set = build_feature_set(
        token,
        [
            FakeSnapshot(captured_at=NOW),
            FakeSnapshot(captured_at=NOW - timedelta(days=30)),
        ],
        now=NOW,
        policy=POLICY,
    )
    assert feature_set.observations == 1


def test_the_window_is_capped_at_k() -> None:
    token = FakeToken(block_time=NOW - timedelta(hours=2))
    snapshots = [
        FakeSnapshot(captured_at=NOW - timedelta(seconds=30 * index)) for index in range(50)
    ]
    feature_set = build_feature_set(
        token, snapshots, now=NOW, policy=POLICY, feature_window=12
    )
    assert feature_set.observations == 12


def test_latest_market_state_comes_from_the_newest_snapshot() -> None:
    token = FakeToken(block_time=NOW - timedelta(hours=2))
    feature_set = build_feature_set(
        token,
        [
            FakeSnapshot(captured_at=NOW - timedelta(minutes=5), liquidity_usd=Decimal(1)),
            FakeSnapshot(captured_at=NOW, liquidity_usd=Decimal(99999)),
        ],
        now=NOW,
        policy=POLICY,
    )
    assert feature_set.liquidity_usd == Decimal(99999)


def test_a_token_with_no_snapshots_is_still_a_valid_feature_set() -> None:
    """Nothing to score is a state to report, not an error to raise."""
    feature_set = build_feature_set(FakeToken(), [], now=NOW, policy=POLICY)

    assert feature_set.observations == 0
    assert feature_set.has_market is False
    assert feature_set.latest_snapshot_at is None
    assert feature_set.trading_status == "unknown"


def test_metadata_resolution_is_normalised_to_a_bool() -> None:
    resolved = build_feature_set(
        FakeToken(metadata_status="resolved"), [], now=NOW, policy=POLICY
    )
    pending = build_feature_set(
        FakeToken(metadata_status="pending"), [], now=NOW, policy=POLICY
    )
    assert resolved.metadata_resolved is True
    assert pending.metadata_resolved is False


def test_prior_elite_streak_is_carried_through() -> None:
    """Path-dependent state enters as an input, never accumulated internally."""
    feature_set = build_feature_set(
        FakeToken(), [], now=NOW, policy=POLICY, prior_elite_streak=2
    )
    assert feature_set.prior_elite_streak == 2


# --- Window helpers -----------------------------------------------------------


def test_liquidity_peak_respects_the_recency_slice() -> None:
    feature_set = features(
        window=(
            Observation(NOW, Decimal("0.001"), Decimal(10000)),
            Observation(NOW - timedelta(hours=2), Decimal("0.009"), Decimal(90000)),
        )
    )
    # The 90k observation is two hours old; a one-hour slice must not see it.
    # This is what separates a rug in progress from decay that already happened.
    assert feature_set.liquidity_peak() == Decimal(90000)
    assert feature_set.liquidity_peak(within_seconds=3600) == Decimal(10000)


def test_liquidity_peak_is_none_without_liquidity() -> None:
    assert features(window=observations(liquidity=None)).liquidity_peak() is None
    assert features(window=()).liquidity_peak() is None


def test_priced_observations_filters_and_preserves_order() -> None:
    feature_set = features(
        window=(*observations(count=2, price="0.002"), *observations(count=1, price=None))
    )
    assert len(feature_set.priced_observations()) == 2


def test_mean_spacing_needs_two_observations() -> None:
    assert features(window=observations(count=1)).mean_spacing_seconds() is None
    assert features(window=()).mean_spacing_seconds() is None
    assert features(window=observations(count=5, spacing_seconds=300)).mean_spacing_seconds() == (
        Decimal(300)
    )


def test_has_market_reflects_provider_coverage() -> None:
    assert features().has_market is True
    assert features(price_usd=None, liquidity_usd=None).has_market is False


def test_evaluated_at_is_supplied_not_read_from_the_clock() -> None:
    """Purity: the engine never calls `datetime.now()`."""
    stamp = datetime(2020, 1, 1, tzinfo=UTC)
    feature_set = build_feature_set(FakeToken(), [], now=stamp, policy=POLICY)
    assert feature_set.evaluated_at == stamp
