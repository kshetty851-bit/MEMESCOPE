"""Lifecycle events: what changed about a meme's attention, and when we knew.

History comes from ``attention_series(state, bucket=1h)``. The state already
holds all visible history, so a detection at ``T`` does not depend on when a
replay started — only on what was known at ``T``.

**Hourly series baseline.** For each complete hourly bucket, the baseline is
the mean of the measured buckets in the preceding ``BASELINE_BUCKETS`` (7 days),
requiring at least ``MIN_BASELINE_BUCKETS`` measured buckets and
``MIN_BASELINE_MENTIONS`` in total — otherwise Unavailable. It is causal (uses
only earlier buckets), so a bucket's classification never changes as more
history arrives.

**Waves** — a state machine over the series, in time order:

* *start*: outside a wave, a measured bucket with rate > 0 and
  ``rate >= increase_multiple x baseline``;
* *end (trough)*: inside a wave, a bucket below
  ``wave_trough_fraction x the wave's running peak``.

Only after a trough can the next rise count as a new wave; one sustained
plateau is one wave however long it lasts. Unmeasured buckets change nothing.

**Events** (all fire at ``detected_at = state.as_of``):

=================================  ==============================================
NEW_ATTENTION_WAVE / SECOND_WAVE    a wave is in progress at as_of; numbered 1 / 2
/ THIRD_WAVE                        / 3+ (THIRD_WAVE covers every wave after the
                                    second). Once per wave.
MEME_REVIVAL                        the latest complete bucket is
                                    ``>= revival_multiple x LB`` after
                                    ``dormant_for`` of *measured* buckets all
                                    ``< dormant_multiple x LB``; LB is the mean of
                                    all measured history before the dormancy.
                                    Dormancy must be observed, not inferred from
                                    gaps. Once per revival bucket.
ATTENTION_DECAY                     the latest measured bucket after the most
                                    recent wave's peak is
                                    ``<= decay_multiple x that peak``. Once per wave.
ATTENTION_INCREASE                  ``baseline_multiple >= increase_multiple``.
ATTENTION_ACCELERATION              ``acceleration >= acceleration_threshold``.
ATTENTION_PRICE_DIVERGENCE          divergence case A (per linked mint).
PRICE_ATTENTION_DIVERGENCE          divergence case D (per linked mint).
CROSS_PLATFORM_EXPANSION            ``platform_count`` exceeds the count recorded
                                    by the previous expansion event, if that event
                                    is within 24h (the activity window); else
                                    exceeds 1.
=================================  ==============================================

**Episodes, so a 5-minute replay does not re-fire every tick.** Wave, decay and
revival events carry an ``episode_key`` (the wave's start bucket / the revival
bucket) and fire once per key. INCREASE, ACCELERATION and the divergences
re-arm only when the condition has been *observed false* at a complete hourly
bucket that starts at or after the previous firing: the bucket's own multiple
or acceleration below threshold, or (divergence) the case at the bucket's end
measurably different. An unmeasured bucket never re-arms — not knowing is not
evidence the episode ended. Prior events from another mode, detector version,
meme, or from after ``as_of`` are ignored.

These are observations. No event is a buy, a sell, or advice.

Pure: no I/O, no clock, no randomness.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, fields
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from app.lifecycle_lab.attention import attention_series
from app.lifecycle_lab.config import EventConfig
from app.lifecycle_lab.divergence import classify_divergence
from app.lifecycle_lab.domain import (
    AgeBucket,
    AttentionFeatures,
    DivergenceCase,
    EventType,
    InformationState,
    MarketFeatures,
    Measured,
    MemeEvent,
    Unavailable,
)
from app.lifecycle_lab.market import price_change_at

HOUR = timedelta(hours=1)
#: 7 days of hourly buckets.
BASELINE_BUCKETS = 168
MIN_BASELINE_BUCKETS = 6
MIN_BASELINE_MENTIONS = Decimal(5)
#: How long a cross-platform expansion is remembered — the platform count
#: itself is measured over a 24h activity window.
CROSS_PLATFORM_MEMORY = timedelta(hours=24)

Series = Sequence[tuple[datetime, Measured]]

_TYPE_ORDER = {t: i for i, t in enumerate(EventType)}


# --------------------------------------------------------------------------
# Series analysis (shared with states.py)
# --------------------------------------------------------------------------


def series_baselines(series: Series) -> list[Measured]:
    """Causal trailing-mean baseline per bucket (see module docstring)."""
    sums = [Decimal(0)]
    counts = [0]
    for _t, v in series:
        measured = isinstance(v, Decimal)
        sums.append(sums[-1] + (v if isinstance(v, Decimal) else Decimal(0)))
        counts.append(counts[-1] + (1 if measured else 0))
    out: list[Measured] = []
    for i in range(len(series)):
        lo = max(0, i - BASELINE_BUCKETS)
        n = counts[i] - counts[lo]
        total = sums[i] - sums[lo]
        if n < MIN_BASELINE_BUCKETS or total < MIN_BASELINE_MENTIONS:
            out.append(Unavailable("insufficient_baseline"))
        else:
            out.append(total / Decimal(n))
    return out


def bucket_multiples(series: Series) -> list[Measured]:
    out: list[Measured] = []
    for (_t, v), b in zip(series, series_baselines(series), strict=True):
        if isinstance(v, Unavailable):
            out.append(v)
        elif isinstance(b, Unavailable):
            out.append(b)
        elif b == 0:
            out.append(Unavailable("zero_denominator"))
        else:
            out.append(v / b)
    return out


def bucket_accelerations(series: Series) -> list[Measured]:
    """``v[i]/v[i-1] - v[i-1]/v[i-2]`` — the attention-feature definition at
    bucket granularity."""
    out: list[Measured] = []
    for i, (_t, v0) in enumerate(series):
        if i < 2:
            out.append(Unavailable("insufficient_history"))
            continue
        v1, v2 = series[i - 1][1], series[i - 2][1]
        if not (
            isinstance(v0, Decimal) and isinstance(v1, Decimal) and isinstance(v2, Decimal)
        ):
            out.append(Unavailable("not_observed"))
        elif v1 == 0 or v2 == 0:
            out.append(Unavailable("zero_denominator"))
        else:
            out.append(v0 / v1 - v1 / v2)
    return out


@dataclass(frozen=True, slots=True)
class Wave:
    number: int
    started_at: datetime
    peak: Decimal
    peak_at: datetime
    #: Start of the trough bucket that ended the wave; None while in progress.
    ended_at: datetime | None


@dataclass(frozen=True, slots=True)
class WaveHistory:
    waves: tuple[Wave, ...]
    in_wave: bool

    @property
    def current(self) -> Wave | None:
        return self.waves[-1] if self.in_wave and self.waves else None

    @property
    def last(self) -> Wave | None:
        return self.waves[-1] if self.waves else None


def wave_history(series: Series, cfg: EventConfig) -> WaveHistory:
    waves: list[Wave] = []
    in_wave = False
    for (t, v), b in zip(series, series_baselines(series), strict=True):
        if not isinstance(v, Decimal):
            continue
        if in_wave:
            wave = waves[-1]
            if v > wave.peak:
                wave = Wave(wave.number, wave.started_at, v, t, None)
            if v < cfg.wave_trough_fraction * wave.peak:
                wave = Wave(wave.number, wave.started_at, wave.peak, wave.peak_at, t)
                in_wave = False
            waves[-1] = wave
        elif isinstance(b, Decimal) and v > 0 and v >= cfg.increase_multiple * b:
            waves.append(Wave(len(waves) + 1, t, v, t, None))
            in_wave = True
    return WaveHistory(tuple(waves), in_wave)


def revival_bucket(series: Series, cfg: EventConfig) -> datetime | None:
    """Start of the latest bucket if it is a revival (module docstring)."""
    if not series:
        return None
    last_t, last_v = series[-1]
    if not isinstance(last_v, Decimal):
        return None
    dormant_n = -(-cfg.dormant_for // HOUR)  # ceil
    if dormant_n < 1 or len(series) < dormant_n + 1:
        return None
    dormant = [v for _t, v in series[-1 - dormant_n : -1]]
    history = [v for _t, v in series[: -1 - dormant_n] if isinstance(v, Decimal)]
    total = sum(history, Decimal(0))
    if len(history) < MIN_BASELINE_BUCKETS or total < MIN_BASELINE_MENTIONS:
        return None
    long_run = total / Decimal(len(history))
    if not all(
        isinstance(v, Decimal) and v < cfg.dormant_multiple * long_run for v in dormant
    ):
        return None
    if last_v >= cfg.revival_multiple * long_run:
        return last_t
    return None


# --------------------------------------------------------------------------
# Snapshot
# --------------------------------------------------------------------------


def json_safe(value: Any) -> Any:
    """Decimals → str, Unavailable → {"unavailable": reason}, datetimes → ISO,
    timedeltas → seconds, enums → value. Recursive and key-sorted."""
    if isinstance(value, Unavailable):
        return {"unavailable": value.reason}
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {str(k): json_safe(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def _features_of(obj: AttentionFeatures | MarketFeatures | None) -> dict[str, Any] | None:
    if obj is None:
        return None
    return {f.name: json_safe(getattr(obj, f.name)) for f in fields(obj)}


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------


def _wave_type(number: int) -> EventType:
    if number == 1:
        return EventType.NEW_ATTENTION_WAVE
    if number == 2:
        return EventType.SECOND_WAVE
    return EventType.THIRD_WAVE


def _stub_attention(t: datetime, meme_id: str, multiple: Measured) -> AttentionFeatures:
    na = Unavailable("not_evaluated")
    return AttentionFeatures(
        as_of=t,
        meme_id=meme_id,
        mentions_5m=na,
        mentions_15m=na,
        mentions_1h=na,
        mentions_6h=na,
        mentions_24h=na,
        velocity=na,
        acceleration=na,
        baseline_multiple=multiple,
        unique_participants=na,
        engagement=na,
        platform_count=na,
        per_source={},
    )


def _stub_market(t: datetime, mint: str, price_change: Measured) -> MarketFeatures:
    na = Unavailable("not_evaluated")
    return MarketFeatures(
        as_of=t,
        mint_address=mint,
        price_usd=na,
        market_cap=na,
        liquidity_usd=na,
        volume_1h=na,
        volume_growth=na,
        price_change=price_change,
        liquidity_change=na,
        token_age=None,
        age_bucket=AgeBucket.UNKNOWN,
        data_age_seconds=na,
    )


def _rearmed(
    last: MemeEvent | None, series: Series, still_true: Callable[[int], bool | None]
) -> bool:
    """True if there was no previous firing, or the condition was measurably
    false at a complete bucket starting at/after it."""
    if last is None:
        return True
    return any(
        t >= last.detected_at and still_true(i) is False for i, (t, _v) in enumerate(series)
    )


def detect_events(
    *,
    state: InformationState,
    attention: AttentionFeatures,
    market: MarketFeatures | None,
    prior_events: Sequence[MemeEvent],
    cfg: EventConfig,
) -> list[MemeEvent]:
    as_of = state.as_of
    prior = [
        e
        for e in prior_events
        if e.meme_id == state.meme.id
        and e.mode is state.mode
        and e.detector_version == cfg.detector_version
        and e.detected_at <= as_of
    ]

    def previous(event_type: EventType, mint: str | None = None) -> list[MemeEvent]:
        return sorted(
            (e for e in prior if e.event_type is event_type and e.mint_address == mint),
            key=lambda e: e.detected_at,
        )

    def seen(event_type: EventType, key: str, mint: str | None = None) -> bool:
        return any(e.features.get("episode_key") == key for e in previous(event_type, mint))

    series = attention_series(state, bucket=HOUR)
    history = wave_history(series, cfg)
    snapshot = {
        "attention": _features_of(attention),
        "market": _features_of(market),
        "hindsight_links": state.hindsight_links,
    }
    contains_backfill = state.contains_backfill or attention.contains_backfill

    out: list[MemeEvent] = []

    def emit(
        event_type: EventType,
        key: str,
        *,
        mint: str | None = None,
        case: DivergenceCase | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        features: dict[str, Any] = {"episode_key": key, **snapshot}
        if extra:
            features["episode"] = json_safe(extra)
        out.append(
            MemeEvent(
                meme_id=state.meme.id,
                event_type=event_type,
                detected_at=as_of,
                mode=state.mode,
                detector_version=cfg.detector_version,
                mint_address=mint,
                divergence_case=case,
                features=features,
                contains_backfill=contains_backfill,
            )
        )

    # Waves — once per wave.
    current = history.current
    if current is not None:
        wave_type = _wave_type(current.number)
        key = current.started_at.isoformat()
        if not seen(wave_type, key):
            emit(
                wave_type,
                key,
                extra={
                    "wave_number": current.number,
                    "wave_started_at": current.started_at,
                    "peak_rate": current.peak,
                },
            )

    # Revival — once per revival bucket.
    revived = revival_bucket(series, cfg)
    if revived is not None and not seen(EventType.MEME_REVIVAL, revived.isoformat()):
        emit(EventType.MEME_REVIVAL, revived.isoformat(), extra={"revival_bucket": revived})

    # Decay from the most recent wave's peak — once per wave.
    last_wave = history.last
    if last_wave is not None:
        after_peak = [
            (t, v) for t, v in series if t > last_wave.peak_at and isinstance(v, Decimal)
        ]
        if after_peak:
            latest_t, latest_v = after_peak[-1]
            key = last_wave.started_at.isoformat()
            if (
                isinstance(latest_v, Decimal)
                and latest_v <= cfg.decay_multiple * last_wave.peak
                and not seen(EventType.ATTENTION_DECAY, key)
            ):
                emit(
                    EventType.ATTENTION_DECAY,
                    key,
                    extra={
                        "wave_number": last_wave.number,
                        "peak_rate": last_wave.peak,
                        "latest_rate": latest_v,
                        "latest_bucket": latest_t,
                    },
                )

    # Re-armed threshold events.
    multiples = bucket_multiples(series)
    accelerations = bucket_accelerations(series)

    def holds(values: list[Measured], threshold: Decimal) -> Callable[[int], bool | None]:
        def check(i: int) -> bool | None:
            value = values[i]
            return None if isinstance(value, Unavailable) else value >= threshold

        return check

    m = attention.baseline_multiple
    if isinstance(m, Decimal) and m >= cfg.increase_multiple:
        last = _last(previous(EventType.ATTENTION_INCREASE))
        if _rearmed(last, series, holds(multiples, cfg.increase_multiple)):
            emit(EventType.ATTENTION_INCREASE, as_of.isoformat())

    a = attention.acceleration
    if isinstance(a, Decimal) and a >= cfg.acceleration_threshold:
        last = _last(previous(EventType.ATTENTION_ACCELERATION))
        if _rearmed(last, series, holds(accelerations, cfg.acceleration_threshold)):
            emit(EventType.ATTENTION_ACCELERATION, as_of.isoformat())

    case = classify_divergence(attention, market, cfg)
    divergence_type = {
        DivergenceCase.A_ATTENTION_UP_PRICE_FLAT: EventType.ATTENTION_PRICE_DIVERGENCE,
        DivergenceCase.D_ATTENTION_DOWN_PRICE_SURGE: EventType.PRICE_ATTENTION_DIVERGENCE,
    }.get(case)
    if divergence_type is not None and market is not None:
        mint = market.mint_address

        def same_case(i: int) -> bool | None:
            t = series[i][0] + HOUR
            change = price_change_at(state.market, mint, t)
            if isinstance(multiples[i], Unavailable) or isinstance(change, Unavailable):
                return None
            then = classify_divergence(
                _stub_attention(t, state.meme.id, multiples[i]),
                _stub_market(t, mint, change),
                cfg,
            )
            return then is case

        last = _last(previous(divergence_type, mint))
        if _rearmed(last, series, same_case):
            emit(divergence_type, as_of.isoformat(), mint=mint, case=case)

    platforms = attention.platform_count
    if isinstance(platforms, Decimal):
        reference = Decimal(1)
        last = _last(previous(EventType.CROSS_PLATFORM_EXPANSION))
        if last is not None and as_of - last.detected_at <= CROSS_PLATFORM_MEMORY:
            reference = _recorded_platforms(last) or reference
        if platforms > reference:
            emit(
                EventType.CROSS_PLATFORM_EXPANSION,
                f"platforms:{platforms}",
                extra={"platform_count": platforms, "previous_platform_count": reference},
            )

    return sorted(out, key=lambda e: (_TYPE_ORDER[e.event_type], e.mint_address or ""))


def _last(events: list[MemeEvent]) -> MemeEvent | None:
    return events[-1] if events else None


def _recorded_platforms(event: MemeEvent) -> Decimal | None:
    episode = event.features.get("episode")
    if not isinstance(episode, dict):
        return None
    try:
        return Decimal(str(episode.get("platform_count")))
    except (InvalidOperation, ValueError):
        return None
