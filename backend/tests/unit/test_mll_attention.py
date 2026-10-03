"""Attention features: discrete mentions, never pro-rated, never zero-for-absent.

The two failure modes these tests exist for: a missing source quietly reading
as "no attention" (which a strategy would see as a quiet meme), and a
publication lag or a straddling window reading as a falling rate.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.lifecycle_lab.attention import attention_features, attention_series, mention_series
from app.lifecycle_lab.config import AttentionConfig
from app.lifecycle_lab.domain import (
    CollectionRun,
    DataClass,
    InformationState,
    LinkMethod,
    Meme,
    MemeTokenLink,
    Metric,
    Observation,
    ResearchMode,
    Source,
    SourceStatus,
    TokenInfo,
    Unavailable,
    ValueKind,
)
from app.lifecycle_lab.pit import information_available_at

pytestmark = pytest.mark.unit

CFG = AttentionConfig()
Q = timedelta(minutes=15)
START = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
MEME = Meme(id="m1", slug="dog", display_name="Dog", tracking_started_at=START)
MINT = "Mint1"


def gdelt(
    start: datetime, end: datetime, per_bucket: Callable[[datetime], int], lag: timedelta = Q
) -> list[Observation]:
    rows = []
    at = start
    while at + Q <= end:
        rows.append(
            Observation(
                source=Source.GDELT,
                metric=Metric.MENTIONS,
                value_kind=ValueKind.WINDOW_COUNT,
                data_class=DataClass.FORWARD,
                source_timestamp=at,
                observed_at=at + Q,
                retrieved_at=at + Q + lag,
                raw_value=Decimal(per_bucket(at)),
                meme_id="m1",
                window_start=at,
                window_end=at + Q,
                query="dog",
            )
        )
        at += Q
    return rows


def window(
    start: datetime,
    end: datetime,
    value: int,
    *,
    source: Source = Source.GDELT,
    metric: Metric = Metric.MENTIONS,
) -> Observation:
    return Observation(
        source=source,
        metric=metric,
        value_kind=ValueKind.WINDOW_COUNT,
        data_class=DataClass.FORWARD,
        source_timestamp=start,
        observed_at=end,
        retrieved_at=end,
        raw_value=Decimal(value),
        meme_id="m1",
        window_start=start,
        window_end=end,
    )


def runs(as_of: datetime, *sources: Source) -> list[CollectionRun]:
    return [
        CollectionRun(
            id=f"{s}",
            source=s,
            status=SourceStatus.AVAILABLE,
            started_at=as_of - timedelta(minutes=2),
            finished_at=as_of - timedelta(minutes=1),
            data_class=DataClass.FORWARD,
        )
        for s in sources
    ]


def state(
    as_of: datetime,
    observations: list[Observation],
    sources: tuple[Source, ...] = (Source.GDELT,),
    links: list[MemeTokenLink] | None = None,
) -> InformationState:
    return information_available_at(
        as_of=as_of,
        mode=ResearchMode.AUTHORITATIVE,
        meme=MEME,
        aliases=[],
        links=links or [],
        tokens=[TokenInfo(MINT, None, None, None, None)],
        observations=observations,
        market=[],
        runs=runs(as_of, *sources),
    )


def steady(_at: datetime) -> int:
    return 3


def test_unavailable_sources_yield_unavailable_not_zero() -> None:
    """With no source answering, "0 mentions" would be a lie a strategy reads
    as a quiet meme. Every feature is Unavailable and the reason names why."""
    as_of = START + timedelta(days=3)
    st = information_available_at(
        as_of=as_of,
        mode=ResearchMode.AUTHORITATIVE,
        meme=MEME,
        aliases=[],
        links=[],
        tokens=[],
        observations=gdelt(START, as_of, steady),
        market=[],
        runs=[],
    )
    f = attention_features(st, CFG)
    for value in (
        f.mentions_1h,
        f.mentions_24h,
        f.velocity,
        f.baseline_multiple,
        f.platform_count,
    ):
        assert isinstance(value, Unavailable)
        assert value != Decimal(0)
    assert isinstance(f.mentions_1h, Unavailable)
    assert "gdelt=never_collected" in f.mentions_1h.reason
    assert f.per_source["gdelt"]["mentions_1h"] == Unavailable("never_collected")


def test_steady_rate_with_publication_lag_reads_steady() -> None:
    """GDELT publishes 15 minutes late. Counting up to as_of would miss the
    newest bucket and read lag as decline; each series is read up to its own
    newest window instead."""
    as_of = START + timedelta(days=3, minutes=7)
    f = attention_features(state(as_of, gdelt(START, as_of, steady)), CFG)
    assert f.mentions_15m == Decimal(3)
    assert f.mentions_1h == Decimal(12)
    assert f.mentions_24h == Decimal(288)
    assert f.velocity == Decimal(1)
    assert f.acceleration == Decimal(0)
    assert f.baseline_multiple == Decimal(1)
    assert f.platform_count == Decimal(1)


def test_span_finer_than_every_source_is_unavailable() -> None:
    as_of = START + timedelta(days=1)
    f = attention_features(state(as_of, gdelt(START, as_of, steady)), CFG)
    assert f.mentions_5m == Unavailable("no_source_at_resolution")


def test_spike_velocity_acceleration_and_baseline_multiple() -> None:
    """Definitions pinned with numbers: velocity = 48/12, acceleration =
    48/12 - 12/12, baseline multiple = 48 / (12 per hour)."""
    as_of = START + timedelta(days=3)
    spike_from = as_of - timedelta(hours=1)
    rows = gdelt(START, as_of, lambda at: 12 if at >= spike_from else 3, lag=timedelta(0))
    f = attention_features(state(as_of, rows), CFG)
    assert f.mentions_1h == Decimal(48)
    assert f.velocity == Decimal(4)
    assert f.acceleration == Decimal(3)
    assert f.baseline_multiple == Decimal(4)


def test_zero_denominator_is_unavailable_never_infinite() -> None:
    as_of = START + timedelta(days=1)
    quiet_until = as_of - timedelta(hours=1)
    rows = gdelt(START, as_of, lambda at: 5 if at >= quiet_until else 0, lag=timedelta(0))
    f = attention_features(state(as_of, rows), CFG)
    assert f.velocity == Unavailable("zero_denominator")
    assert f.acceleration == Unavailable("zero_denominator")
    # The baseline had no mentions at all: below min_baseline_mentions.
    assert f.baseline_multiple == Unavailable("insufficient_baseline")


def test_short_history_is_insufficient_for_velocity() -> None:
    as_of = START + timedelta(hours=1, minutes=30)
    f = attention_features(state(as_of, gdelt(START, as_of, steady, lag=timedelta(0))), CFG)
    assert f.velocity == Unavailable("insufficient_history")
    assert f.mentions_1h == Decimal(12)


def test_straddling_window_is_not_pro_rated() -> None:
    """A window crossing the 1h boundary is left out, not split: the source
    never said how those mentions were distributed in time."""
    a = START + timedelta(hours=5)
    rows = [
        window(a - 3 * Q, a - 2 * Q, 1),
        window(a - 2 * Q, a - Q, 1),
        window(a - Q, a, 1),
        window(a - timedelta(minutes=75), a - 3 * Q, 100),  # straddles a-1h
    ]
    f = attention_features(state(a, rows), CFG)
    assert f.mentions_1h == Decimal(3)
    assert f.mentions_6h == Decimal(103)


def test_series_behind_the_freshness_budget_is_not_now() -> None:
    """A source whose newest window is older than its freshness budget (GDELT:
    7h) says nothing about the last hour; reading it as 0 would invent a
    collapse."""
    as_of = START + timedelta(days=1)
    rows = gdelt(START, as_of - timedelta(hours=8), steady, lag=timedelta(0))
    f = attention_features(state(as_of, rows), CFG)
    assert f.mentions_1h == Unavailable("no_recent_observation")


def _reply(minute: int, total: int) -> Observation:
    at = START + timedelta(minutes=minute)
    return Observation(
        source=Source.PUMPFUN_REPLIES,
        metric=Metric.REPLIES_TOTAL,
        value_kind=ValueKind.CUMULATIVE,
        data_class=DataClass.FORWARD,
        source_timestamp=at,
        observed_at=at,
        retrieved_at=at,
        raw_value=Decimal(total),
        mint_address=MINT,
    )


def test_cumulative_replies_become_deltas_with_gaps_and_decreases_dropped() -> None:
    """Across a collection gap we do not know when replies happened; a falling
    counter is a correction. Both yield no window — not a zero."""
    rows = [
        _reply(0, 10),
        _reply(5, 12),
        _reply(10, 12),
        _reply(15, 20),
        _reply(40, 30),  # 25-minute gap > 2 x 5
        _reply(45, 25),  # decrease
        _reply(50, 26),
    ]
    lk = MemeTokenLink("m1", MINT, LinkMethod.MANUAL, Decimal(1), START - timedelta(days=1))
    st = state(START + timedelta(hours=1), rows, (Source.PUMPFUN_REPLIES,), links=[lk])
    (windows,) = mention_series(st).values()
    assert [(w.start.minute, w.end.minute, w.value) for w in windows] == [
        (0, 5, Decimal(2)),
        (5, 10, Decimal(0)),
        (10, 15, Decimal(8)),
        (45, 50, Decimal(1)),
    ]


def test_pageviews_are_not_mentions_but_count_as_a_platform() -> None:
    as_of = START + timedelta(days=3, hours=6)
    day = timedelta(days=1)
    views = [
        window(START, START + day, 100, source=Source.WIKIPEDIA, metric=Metric.PAGEVIEWS),
        window(
            START + day, START + 2 * day, 100, source=Source.WIKIPEDIA, metric=Metric.PAGEVIEWS
        ),
        window(
            START + 2 * day,
            START + 3 * day,
            400,
            source=Source.WIKIPEDIA,
            metric=Metric.PAGEVIEWS,
        ),
    ]
    rows = gdelt(START, as_of, steady, lag=timedelta(0)) + views
    f = attention_features(state(as_of, rows, (Source.GDELT, Source.WIKIPEDIA)), CFG)
    assert f.mentions_24h == Decimal(288)
    assert f.per_source["wikipedia"] == {
        "daily_views": Decimal(400),
        "views_baseline_multiple": Decimal(4),
    }
    assert f.platform_count == Decimal(2)


def test_participants_and_engagement_without_a_source_are_unavailable() -> None:
    as_of = START + timedelta(days=1)
    f = attention_features(state(as_of, gdelt(START, as_of, steady)), CFG)
    assert f.unique_participants == Unavailable("no_source")
    assert f.engagement == Unavailable("no_source")


def test_attention_series_buckets_are_epoch_aligned_and_gaps_are_unobserved() -> None:
    as_of = START + timedelta(hours=5, minutes=20)
    rows = gdelt(START, START + 2 * timedelta(hours=1), steady, lag=timedelta(0))
    rows += gdelt(START + timedelta(hours=3), as_of, steady, lag=timedelta(0))
    series = attention_series(state(as_of, rows), bucket=timedelta(hours=1))
    assert [t.hour for t, _ in series] == [0, 1, 2, 3, 4]
    assert [v for _, v in series] == [
        Decimal(12),
        Decimal(12),
        Unavailable("not_observed"),
        Decimal(12),
        Decimal(12),
    ]


def test_features_are_identical_for_shuffled_inputs() -> None:
    as_of = START + timedelta(days=3)
    rows = gdelt(START, as_of, lambda at: (at.hour * 7 + at.minute) % 11)
    first = attention_features(state(as_of, rows), CFG)
    rng = random.Random(11)
    for _ in range(3):
        rng.shuffle(rows)
        assert attention_features(state(as_of, rows), CFG) == first


def test_low_priority_gdelt_cadence_still_speaks_for_now() -> None:
    """A LOW-priority meme is asked about every 6h. Between collections its
    newest GDELT window is up to ~6h old; inside the 7h budget it is still the
    latest knowledge, not an absence — so platform counts track attention,
    not the scheduler."""
    as_of = START + timedelta(days=1)
    rows = gdelt(START, as_of - timedelta(hours=5, minutes=45), steady, lag=timedelta(0))
    st = information_available_at(
        as_of=as_of,
        mode=ResearchMode.AUTHORITATIVE,
        meme=MEME,
        aliases=[],
        links=[],
        tokens=[],
        observations=rows,
        market=[],
        runs=[
            CollectionRun(
                "r",
                Source.GDELT,
                SourceStatus.AVAILABLE,
                as_of - timedelta(hours=6),
                as_of - timedelta(hours=5, minutes=50),
                DataClass.FORWARD,
            )
        ],
    )
    f = attention_features(st, CFG)
    assert f.mentions_1h == Decimal(12)
    assert f.platform_count == Decimal(1)
