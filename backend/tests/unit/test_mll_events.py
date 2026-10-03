"""Event detection, lifecycle states and divergence cases.

The property that matters most for a replay running every five minutes: an
event fires once per episode, not once per tick. And detection reads only the
visible history in the state, so where a replay started cannot change which
wave a meme is in.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.lifecycle_lab.attention import attention_features
from app.lifecycle_lab.config import AttentionConfig, EventConfig
from app.lifecycle_lab.divergence import classify_divergence
from app.lifecycle_lab.domain import (
    AgeBucket,
    AttentionFeatures,
    CollectionRun,
    DataClass,
    DivergenceCase,
    EventType,
    InformationState,
    LifecycleState,
    LinkMethod,
    MarketFeatures,
    MarketPoint,
    Meme,
    MemeEvent,
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
from app.lifecycle_lab.events import detect_events
from app.lifecycle_lab.market import market_features
from app.lifecycle_lab.pit import information_available_at
from app.lifecycle_lab.states import classify_state

pytestmark = pytest.mark.unit

ACFG = AttentionConfig()
ECFG = EventConfig()
Q = timedelta(minutes=15)
H = timedelta(hours=1)
START = datetime(2026, 9, 1, tzinfo=UTC)
MEME = Meme(id="m1", slug="dog", display_name="Dog", tracking_started_at=START)
MINT = "Mint1"
LINK = MemeTokenLink("m1", MINT, LinkMethod.MANUAL, Decimal(1), START - timedelta(days=1))


def gdelt(end: datetime, per_bucket: Callable[[datetime], int]) -> list[Observation]:
    rows, at = [], START
    while at + Q <= end:
        rows.append(
            Observation(
                source=Source.GDELT,
                metric=Metric.MENTIONS,
                value_kind=ValueKind.WINDOW_COUNT,
                data_class=DataClass.FORWARD,
                source_timestamp=at,
                observed_at=at + Q,
                retrieved_at=at + Q,
                raw_value=Decimal(per_bucket(at)),
                meme_id="m1",
                window_start=at,
                window_end=at + Q,
            )
        )
        at += Q
    return rows


def prices(end: datetime, price: Callable[[datetime], Decimal]) -> list[MarketPoint]:
    out, at = [], end - timedelta(hours=12)
    while at <= end:
        out.append(MarketPoint(MINT, at, at, DataClass.FORWARD, price(at)))
        at += timedelta(minutes=5)
    return out


def build(
    as_of: datetime, observations: list[Observation], market: list[MarketPoint] | None = None
) -> InformationState:
    run = CollectionRun(
        id="r",
        source=Source.GDELT,
        status=SourceStatus.AVAILABLE,
        started_at=as_of - timedelta(minutes=2),
        finished_at=as_of - timedelta(minutes=1),
        data_class=DataClass.FORWARD,
    )
    return information_available_at(
        as_of=as_of,
        mode=ResearchMode.AUTHORITATIVE,
        meme=MEME,
        aliases=[],
        links=[LINK],
        tokens=[TokenInfo(MINT, None, None, None, None)],
        observations=observations,
        market=market or [],
        runs=[run],
    )


def replay(
    start: datetime,
    end: datetime,
    observations: list[Observation],
    market: list[MarketPoint] | None = None,
) -> list[MemeEvent]:
    fired: list[MemeEvent] = []
    at = start
    while at <= end:
        st = build(at, observations, market)
        attn = attention_features(st, ACFG)
        mkt = market_features(st, MINT) if market else None
        fired += detect_events(
            state=st, attention=attn, market=mkt, prior_events=fired, cfg=ECFG
        )
        at += timedelta(minutes=5)
    return fired


def types(events: list[MemeEvent]) -> list[EventType]:
    return [e.event_type for e in events]


SPIKE = START + timedelta(days=3)


def one_spike(at: datetime) -> int:
    return 15 if SPIKE <= at < SPIKE + 3 * H else 3


def two_spikes(at: datetime) -> int:
    second = SPIKE + 8 * H
    return 15 if (SPIKE <= at < SPIKE + 3 * H or second <= at < second + 2 * H) else 3


def test_a_five_minute_replay_fires_each_episode_once() -> None:
    """84 ticks across one spike: the wave, the increase and the decay each
    fire exactly once. Re-firing every tick would turn one observation into
    eighty and swamp every downstream count."""
    end = SPIKE + 7 * H
    rows = gdelt(end, one_spike)
    fired = replay(SPIKE - H, end, rows)
    counts = {t: types(fired).count(t) for t in set(types(fired))}
    assert counts[EventType.NEW_ATTENTION_WAVE] == 1
    assert counts[EventType.ATTENTION_INCREASE] == 1
    assert counts[EventType.ATTENTION_DECAY] == 1
    assert EventType.SECOND_WAVE not in counts
    wave = next(e for e in fired if e.event_type is EventType.NEW_ATTENTION_WAVE)
    # The first spike bucket completes at SPIKE + 1h: no earlier knowledge.
    assert wave.detected_at == SPIKE + H
    assert wave.features["episode"]["wave_started_at"] == SPIKE.isoformat()


def test_second_wave_needs_a_trough_and_is_counted_from_visible_history() -> None:
    """A replay that starts after the first wave still calls the next one the
    second wave: the count comes from the state's history, not the replay."""
    end = SPIKE + 12 * H
    rows = gdelt(end, two_spikes)
    full = replay(SPIKE - H, end, rows)
    assert types(full).count(EventType.NEW_ATTENTION_WAVE) == 1
    assert types(full).count(EventType.SECOND_WAVE) == 1

    late = replay(SPIKE + 8 * H, end, rows)
    assert EventType.NEW_ATTENTION_WAVE not in types(late)
    assert types(late).count(EventType.SECOND_WAVE) == 1
    second_full = next(e for e in full if e.event_type is EventType.SECOND_WAVE)
    second_late = next(e for e in late if e.event_type is EventType.SECOND_WAVE)
    assert second_full.detected_at == second_late.detected_at


def test_revival_after_observed_dormancy() -> None:
    revive_at = START + timedelta(days=5)

    def shape(at: datetime) -> int:
        if at < START + timedelta(days=3):
            return 3
        if at < revive_at:
            return 1 if at.minute == 0 else 0
        return 10

    end = revive_at + 2 * H
    fired = replay(revive_at, end, gdelt(end, shape))
    revivals = [e for e in fired if e.event_type is EventType.MEME_REVIVAL]
    assert len(revivals) == 1
    assert revivals[0].detected_at == revive_at + H


def test_attention_up_price_flat_divergence_names_the_mint_once() -> None:
    end = SPIKE + 3 * H
    rows = gdelt(end, one_spike)
    fired = replay(SPIKE, end, rows, prices(end, lambda _at: Decimal("0.01")))
    div = [e for e in fired if e.event_type is EventType.ATTENTION_PRICE_DIVERGENCE]
    assert len(div) == 1
    assert div[0].mint_address == MINT
    assert div[0].divergence_case is DivergenceCase.A_ATTENTION_UP_PRICE_FLAT


def test_events_carry_provenance_and_json_safe_neutral_features() -> None:
    end = SPIKE + 2 * H
    fired = replay(SPIKE, end, gdelt(end, one_spike))
    assert fired
    for event in fired:
        assert event.mode is ResearchMode.AUTHORITATIVE
        assert event.detector_version == ECFG.detector_version
        assert event.contains_backfill is False
        text = json.dumps(event.features)  # raises on Decimal / Unavailable
        assert not re.search(r"\b(buy|sell|hold|consider)\b", text, re.IGNORECASE)


def test_prior_events_from_another_mode_or_version_do_not_suppress() -> None:
    end = SPIKE + 2 * H
    st = build(end, gdelt(end, one_spike))
    attn = attention_features(st, ACFG)
    first = detect_events(state=st, attention=attn, market=None, prior_events=[], cfg=ECFG)
    assert first
    again = detect_events(state=st, attention=attn, market=None, prior_events=first, cfg=ECFG)
    assert again == []
    other = [replace(e, mode=ResearchMode.EXPLORATORY) for e in first]
    other += [replace(e, detector_version="old") for e in first]
    assert (
        detect_events(state=st, attention=attn, market=None, prior_events=other, cfg=ECFG)
        == first
    )


def test_cross_platform_expansion_fires_on_a_rise_only() -> None:
    end = SPIKE - 2 * H
    st = build(end, gdelt(end, lambda _at: 3))
    attn = attention_features(st, ACFG)
    assert (
        detect_events(state=st, attention=attn, market=None, prior_events=[], cfg=ECFG) == []
    )

    two = replace(attn, platform_count=Decimal(2))
    fired = detect_events(state=st, attention=two, market=None, prior_events=[], cfg=ECFG)
    assert types(fired) == [EventType.CROSS_PLATFORM_EXPANSION]

    later = build(end + timedelta(minutes=5), gdelt(end, lambda _at: 3))
    attn2 = replace(attention_features(later, ACFG), platform_count=Decimal(2))
    assert (
        detect_events(state=later, attention=attn2, market=None, prior_events=fired, cfg=ECFG)
        == []
    )
    three = replace(attn2, platform_count=Decimal(3))
    assert types(
        detect_events(state=later, attention=three, market=None, prior_events=fired, cfg=ECFG)
    ) == [EventType.CROSS_PLATFORM_EXPANSION]


# --------------------------------------------------------------------------
# States
# --------------------------------------------------------------------------


def _state_at(as_of: datetime, shape: Callable[[datetime], int]) -> tuple:
    st = build(as_of, gdelt(as_of, shape))
    return st, attention_features(st, ACFG)


def test_state_unknown_when_attention_unavailable() -> None:
    st = build(SPIKE, [])
    attn = attention_features(st, ACFG)
    assert isinstance(attn.mentions_1h, Unavailable)
    assert (
        classify_state(state=st, attention=attn, market=None, prior_events=[], cfg=ECFG)
        is LifecycleState.UNKNOWN
    )


@pytest.mark.parametrize(
    ("as_of", "expected"),
    [
        (SPIKE - 2 * H, LifecycleState.ACTIVE),
        (SPIKE + 2 * H, LifecycleState.EMERGING),
        (SPIKE + 5 * H, LifecycleState.DECAYING),
    ],
)
def test_state_follows_the_wave(as_of: datetime, expected: LifecycleState) -> None:
    st, attn = _state_at(as_of, one_spike)
    assert (
        classify_state(state=st, attention=attn, market=None, prior_events=[], cfg=ECFG)
        is expected
    )


def test_state_pumping_on_price_surge() -> None:
    as_of = SPIKE - 2 * H
    rows = gdelt(as_of, lambda _at: 3)
    points = prices(as_of, lambda at: Decimal("2") if at > as_of - H else Decimal("1"))
    st = build(as_of, rows, points)
    attn = attention_features(st, ACFG)
    mkt = market_features(st, MINT)
    assert mkt.price_change == Decimal(1)
    assert (
        classify_state(state=st, attention=attn, market=mkt, prior_events=[], cfg=ECFG)
        is LifecycleState.PUMPING
    )


# --------------------------------------------------------------------------
# Divergence
# --------------------------------------------------------------------------


def _attn(multiple: Decimal | Unavailable) -> AttentionFeatures:
    na = Unavailable("x")
    return AttentionFeatures(
        SPIKE, "m1", na, na, na, na, na, na, na, multiple, na, na, na, per_source={}
    )


def _mkt(change: Decimal | Unavailable) -> MarketFeatures:
    na = Unavailable("x")
    return MarketFeatures(
        SPIKE, MINT, na, na, na, na, na, change, na, None, AgeBucket.UNKNOWN, na
    )


@pytest.mark.parametrize(
    ("multiple", "change", "case"),
    [
        ("4", "0.01", DivergenceCase.A_ATTENTION_UP_PRICE_FLAT),
        ("4", "0.2", DivergenceCase.B_ATTENTION_UP_PRICE_UP),
        ("4", "0.9", DivergenceCase.C_ATTENTION_UP_PRICE_SURGE),
        ("0.5", "0.9", DivergenceCase.D_ATTENTION_DOWN_PRICE_SURGE),
        ("0.3", "-0.2", DivergenceCase.E_ATTENTION_DOWN_PRICE_DOWN),
        ("0.6", "-0.2", DivergenceCase.NONE),  # mild drift both ways: not E
        ("4", "-0.2", DivergenceCase.NONE),
        ("1", "0.01", DivergenceCase.NONE),
    ],
)
def test_divergence_cases(multiple: str, change: str, case: DivergenceCase) -> None:
    assert classify_divergence(_attn(Decimal(multiple)), _mkt(Decimal(change)), ECFG) is case


def test_divergence_none_when_inputs_unavailable() -> None:
    assert (
        classify_divergence(_attn(Unavailable("x")), _mkt(Decimal(0)), ECFG)
        is DivergenceCase.NONE
    )
    assert (
        classify_divergence(_attn(Decimal(4)), _mkt(Unavailable("x")), ECFG)
        is DivergenceCase.NONE
    )
    assert classify_divergence(_attn(Decimal(4)), None, ECFG) is DivergenceCase.NONE


def test_events_are_identical_for_shuffled_inputs() -> None:
    """Database row order is not a contract: the same rows in any order must
    yield the same events, byte for byte."""
    import random

    end = SPIKE + 2 * H
    rows = gdelt(end, one_spike)
    market = prices(end, lambda at: Decimal("0.01"))
    st = build(end, rows, market)
    first = detect_events(
        state=st,
        attention=attention_features(st, ACFG),
        market=market_features(st, MINT),
        prior_events=[],
        cfg=ECFG,
    )
    assert first
    rng = random.Random(13)
    for _ in range(3):
        rng.shuffle(rows)
        rng.shuffle(market)
        again = build(end, rows, market)
        assert (
            detect_events(
                state=again,
                attention=attention_features(again, ACFG),
                market=market_features(again, MINT),
                prior_events=[],
                cfg=ECFG,
            )
            == first
        )


def test_memoised_series_cannot_be_corrupted_by_a_caller() -> None:
    """The per-state memo changes cost, never results: mutating a returned
    series must not leak into the next call."""
    from app.lifecycle_lab.attention import attention_series

    st = build(SPIKE, gdelt(SPIKE, one_spike))
    first = attention_series(st, bucket=H)
    snapshot = list(first)
    first.clear()
    assert attention_series(st, bucket=H) == snapshot
    assert attention_series(st, bucket=H, until=SPIKE - 2 * H) == snapshot[:-2]
