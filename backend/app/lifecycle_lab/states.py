"""Descriptive lifecycle state of a meme at ``state.as_of``.

A label for what attention is doing, never what to do about it. The first
matching rule wins, in this order:

1.  UNKNOWN       — ``mentions_1h`` is Unavailable. We do not guess a state
                    from missing data.
2.  DEAD          — no mentions in 24h, at least ``DEAD_AFTER`` (7 days) of
                    trailing hourly buckets all measured and zero, and some
                    earlier bucket nonzero (a meme never mentioned is not dead,
                    it is untracked noise — DORMANT).
3.  PUMPING       — the linked market's price change >= ``price_surge``. Price
                    is the most visible fact when it surges, so it outranks the
                    attention labels.
4.  REVIVING      — the latest bucket is a revival, or a MEME_REVIVAL fired at
                    or after the current wave began.
5.  THIRD_WAVE    — inside wave number 3 or later.
6.  SECOND_WAVE   — inside wave number 2.
7.  ACCELERATING  — ``acceleration >= acceleration_threshold``.
8.  EMERGING      — inside the first wave.
9.  DECAYING      — the most recent wave ended within the last 24h.
10. DORMANT       — ``baseline_multiple <= dormant_multiple`` or no mentions
                    in 24h.
11. COOLING       — ``velocity < 1``.
12. ACTIVE        — attention is measured and none of the above applies.

Pure: no I/O, no clock, no randomness.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal

from app.lifecycle_lab.attention import attention_series
from app.lifecycle_lab.config import EventConfig
from app.lifecycle_lab.domain import (
    AttentionFeatures,
    EventType,
    InformationState,
    LifecycleState,
    MarketFeatures,
    MemeEvent,
)
from app.lifecycle_lab.events import revival_bucket, wave_history

HOUR = timedelta(hours=1)
DEAD_AFTER = timedelta(days=7)
RECENT = timedelta(hours=24)


def classify_state(
    *,
    state: InformationState,
    attention: AttentionFeatures,
    market: MarketFeatures | None,
    prior_events: Sequence[MemeEvent],
    cfg: EventConfig,
) -> LifecycleState:
    as_of = state.as_of
    m1h = attention.mentions_1h
    if not isinstance(m1h, Decimal):
        return LifecycleState.UNKNOWN

    series = attention_series(state, bucket=HOUR)
    m24 = attention.mentions_24h
    quiet_day = isinstance(m24, Decimal) and m24 == 0

    dead_n = DEAD_AFTER // HOUR
    if quiet_day and len(series) > dead_n:
        tail = [v for _t, v in series[-dead_n:]]
        earlier = [v for _t, v in series[:-dead_n] if isinstance(v, Decimal)]
        if all(isinstance(v, Decimal) and v == 0 for v in tail) and any(
            v > 0 for v in earlier
        ):
            return LifecycleState.DEAD

    if market is not None:
        change = market.price_change
        if isinstance(change, Decimal) and change >= cfg.price_surge:
            return LifecycleState.PUMPING

    history = wave_history(series, cfg)
    current = history.current

    revivals = [
        e
        for e in prior_events
        if e.event_type is EventType.MEME_REVIVAL
        and e.meme_id == state.meme.id
        and e.mode is state.mode
        and e.detector_version == cfg.detector_version
        and e.detected_at <= as_of
    ]
    if revival_bucket(series, cfg) is not None or (
        current is not None and any(e.detected_at >= current.started_at for e in revivals)
    ):
        return LifecycleState.REVIVING

    if current is not None and current.number >= 3:
        return LifecycleState.THIRD_WAVE
    if current is not None and current.number == 2:
        return LifecycleState.SECOND_WAVE

    acceleration = attention.acceleration
    if isinstance(acceleration, Decimal) and acceleration >= cfg.acceleration_threshold:
        return LifecycleState.ACCELERATING

    if current is not None:
        return LifecycleState.EMERGING

    last = history.last
    if last is not None and last.ended_at is not None and as_of - last.ended_at <= RECENT:
        return LifecycleState.DECAYING

    multiple = attention.baseline_multiple
    if quiet_day or (isinstance(multiple, Decimal) and multiple <= cfg.dormant_multiple):
        return LifecycleState.DORMANT

    velocity = attention.velocity
    if isinstance(velocity, Decimal) and velocity < 1:
        return LifecycleState.COOLING

    return LifecycleState.ACTIVE
