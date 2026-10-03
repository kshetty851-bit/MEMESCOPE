"""Attention features from an ``InformationState``.

**What counts as a mention.** A *discrete* mention is one post, article or
reply. Two kinds of row carry them:

* ``Metric.MENTIONS`` window counts (GDELT 15-minute buckets, Reddit, X) —
  taken as reported;
* ``Metric.REPLIES_TOTAL`` cumulative counters (pump.fun) — turned into window
  counts by differencing consecutive readings of the same subject. A pair whose
  spacing exceeds twice the series' typical (median) spacing, or whose counter
  went *down*, yields **no** window, not a zero: across a collection gap we do
  not know when the replies happened, and a decreasing counter is a source
  correction, not negative attention.

Page views are not mentions — a view is not an utterance, and one Wikipedia
day would swamp every hourly count. They are reported separately under
``per_source["wikipedia"]`` and count toward ``platform_count``.

**Never pro-rate.** A window contributes to a span only if it lies *fully*
inside it. A 15-minute bucket straddling the 1h boundary is not split 1/3-2/3;
it is left out of the 1h count. Pro-rating invents a time distribution the
source never reported. A span shorter than every available source's resolution
is ``Unavailable("no_source_at_resolution")`` rather than an undercount.

**Absence is never zero.** Only sources whose collection status is AVAILABLE at
``as_of`` contribute. If none is, every feature is Unavailable and the reason
names each source's status. Any ratio with a zero denominator is
``Unavailable("zero_denominator")`` — never infinity, never 0.

**Series.** Aggregation is per *series* — one (source, subject) pair, where the
subject is the meme itself or one linked mint. Several queries for the same
series and window (aliases searched separately) overlap in the articles they
find, so they are combined with ``max``, not summed; distinct series (two
linked mints, two platforms) are distinct mentions and are summed.

Definitions:

"Now" for each series is its newest complete window end (never after as_of,
and only if within the source's freshness budget) — see ``LiveSeries``. Below, "the
last hour" means (anchor - 1h, anchor] per series, summed across series.

* ``velocity`` = mentions in the last hour ÷ mentions in the hour before it.
* ``acceleration`` = velocity now - velocity one hour earlier, i.e.
  ``c0/c1 - c1/c2`` for the three trailing hours ``c0, c1, c2`` (newest first).
  A *difference* of ratios, so 1.5 means "the hour-over-hour growth ratio rose
  by 1.5" (e.g. from 1.0x to 2.5x). Only series observed since the start of
  the oldest hour compared take part, so a source switching on mid-comparison
  cannot look like a surge.
* ``baseline_multiple`` = mentions in the last hour ÷ the series' mean hourly
  rate over [as_of - baseline_window, as_of - baseline_gap]. The mean is taken
  over the *observed* duration (union of the counted windows) per series and
  summed across series, so a source that started two days ago is not diluted
  over seven.

Pure: no I/O, no clock, no randomness.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Any, TypeVar

from app.lifecycle_lab.config import AttentionConfig
from app.lifecycle_lab.domain import (
    ATTENTION_SOURCES,
    AttentionFeatures,
    DataClass,
    InformationState,
    Measured,
    Metric,
    Observation,
    Source,
    SourceAvailability,
    SourceStatus,
    Unavailable,
    ValueKind,
)
from app.lifecycle_lab.pit import freshness_budgets, observation_key

HOUR = timedelta(hours=1)
DAY = timedelta(days=1)

NO_SOURCE_AT_RESOLUTION = "no_source_at_resolution"
ZERO_DENOMINATOR = "zero_denominator"
INSUFFICIENT_HISTORY = "insufficient_history"
INSUFFICIENT_BASELINE = "insufficient_baseline"
NO_SOURCE = "no_source"
NOT_OBSERVED = "not_observed"
NO_RECENT_OBSERVATION = "no_recent_observation"

#: (feature name, span) for the windowed mention counts.
MENTION_WINDOWS: tuple[tuple[str, timedelta], ...] = (
    ("mentions_5m", timedelta(minutes=5)),
    ("mentions_15m", timedelta(minutes=15)),
    ("mentions_1h", HOUR),
    ("mentions_6h", timedelta(hours=6)),
    ("mentions_24h", DAY),
)

#: Window-count metrics that are evidence of *activity* for platform_count.
_ACTIVITY_METRICS = frozenset(
    {Metric.MENTIONS, Metric.PAGEVIEWS, Metric.UNIQUE_PARTICIPANTS, Metric.ENGAGEMENT}
)

ATTENTION_ORDER: tuple[Source, ...] = tuple(sorted(ATTENTION_SOURCES, key=lambda s: s.value))


@dataclass(frozen=True, slots=True)
class Window:
    """Discrete mentions inside [start, end)."""

    start: datetime
    end: datetime
    value: Decimal


SeriesKey = tuple[Source, str]


# --------------------------------------------------------------------------
# Small exact helpers
# --------------------------------------------------------------------------


def _micros(span: timedelta) -> int:
    return span // timedelta(microseconds=1)


def _hours(span: timedelta) -> Decimal:
    return Decimal(_micros(span)) / Decimal(_micros(HOUR))


def _median_low(spans: Sequence[timedelta]) -> timedelta:
    ordered = sorted(spans)
    return ordered[(len(ordered) - 1) // 2]


def _floor(t: datetime, bucket: timedelta) -> datetime:
    """Epoch-aligned bucket start, so buckets never depend on when a replay
    began."""
    epoch = datetime(1970, 1, 1, tzinfo=t.tzinfo)
    return epoch + ((t - epoch) // bucket) * bucket


def ratio(numerator: Decimal, denominator: Decimal) -> Measured:
    if denominator == 0:
        return Unavailable(ZERO_DENOMINATOR)
    return numerator / denominator


def _subject(obs: Observation) -> str:
    return f"meme:{obs.meme_id}" if obs.meme_id is not None else f"mint:{obs.mint_address}"


def _preference(obs: Observation) -> tuple[Any, ...]:
    """Which of several readings of the same thing to keep: FORWARD first (it
    is what was known then), then the earliest retrieved (first write wins, as
    in the store), then the gate's total order."""
    return (
        0 if obs.data_class is DataClass.FORWARD else 1,
        obs.retrieved_at,
        observation_key(obs),
    )


# --------------------------------------------------------------------------
# Per-state memo
# --------------------------------------------------------------------------

_T = TypeVar("_T")
_MEMO: dict[tuple[int, str], tuple[InformationState, Any]] = {}
_MEMO_LIMIT = 64


def _memoised(state: InformationState, tag: str, build: Callable[[], _T]) -> _T:
    """Derived views of one ``InformationState``, computed once.

    A replay tick asks for the same mention series three times (features,
    events, states); rebuilding it each time was most of the replay's cost.
    The memo is keyed on the state's *identity* and holds a strong reference
    to it, so an id cannot be recycled while cached, and a state is immutable,
    so a hit is always exactly what a rebuild would return. It changes cost,
    never results — determinism and purity are unaffected. Bounded: cleared
    whole when full.
    """
    key = (id(state), tag)
    hit = _MEMO.get(key)
    if hit is not None and hit[0] is state:
        value: _T = hit[1]
        return value
    built = build()
    if len(_MEMO) >= _MEMO_LIMIT:
        _MEMO.clear()
    _MEMO[key] = (state, built)
    return built


def _by_metric(state: InformationState) -> dict[Metric, tuple[Observation, ...]]:
    """Attention-source observations partitioned by metric, in one pass."""

    def build() -> dict[Metric, tuple[Observation, ...]]:
        out: dict[Metric, list[Observation]] = {}
        for obs in state.observations:
            if obs.source in ATTENTION_SOURCES:
                out.setdefault(obs.metric, []).append(obs)
        return {m: tuple(rows) for m, rows in out.items()}

    return _memoised(state, "by_metric", build)


def _window_counts(
    observations: Iterable[Observation], metric: Metric, sources: frozenset[Source]
) -> dict[SeriesKey, list[Window]]:
    """Window-count rows of ``metric``: one preferred reading per (series,
    query, window), then ``max`` across queries per (series, window)."""
    chosen: dict[tuple[Source, str, str, datetime, datetime], Observation] = {}
    for obs in observations:
        if obs.metric is not metric or obs.source not in sources:
            continue
        if obs.value_kind is not ValueKind.WINDOW_COUNT:
            continue
        if obs.window_start is None or obs.window_end is None:
            continue
        if obs.window_end <= obs.window_start:
            continue
        key = (obs.source, _subject(obs), obs.query or "", obs.window_start, obs.window_end)
        current = chosen.get(key)
        if current is None or _preference(obs) < _preference(current):
            chosen[key] = obs
    merged: dict[tuple[Source, str, datetime, datetime], Decimal] = {}
    for (source, subject, _query, start, end), obs in chosen.items():
        slot = (source, subject, start, end)
        merged[slot] = max(merged.get(slot, obs.raw_value), obs.raw_value)
    series: dict[SeriesKey, list[Window]] = {}
    for (source, subject, start, end), value in merged.items():
        series.setdefault((source, subject), []).append(Window(start, end, value))
    for windows in series.values():
        windows.sort(key=lambda w: (w.start, w.end))
    return series


def _cumulative_deltas(observations: Iterable[Observation]) -> dict[SeriesKey, list[Window]]:
    groups: dict[tuple[Source, str, str], dict[datetime, Observation]] = {}
    for obs in observations:
        if obs.metric is not Metric.REPLIES_TOTAL or obs.source not in ATTENTION_SOURCES:
            continue
        if obs.value_kind is not ValueKind.CUMULATIVE:
            continue
        readings = groups.setdefault((obs.source, _subject(obs), obs.query or ""), {})
        current = readings.get(obs.observed_at)
        if current is None or _preference(obs) < _preference(current):
            readings[obs.observed_at] = obs

    # Several queries for one subject would double-count the same replies:
    # keep the best-sampled one (most readings; ties on the query text, so the
    # choice never depends on input order).
    best: dict[SeriesKey, tuple[int, str, list[Observation]]] = {}
    for (source, subject, query), readings in groups.items():
        ordered = [readings[t] for t in sorted(readings)]
        incumbent = best.get((source, subject))
        if incumbent is None or (len(ordered), query) > (incumbent[0], incumbent[1]):
            best[(source, subject)] = (len(ordered), query, ordered)

    series: dict[SeriesKey, list[Window]] = {}
    for key, (_count, _query, ordered) in best.items():
        spacings = [b.observed_at - a.observed_at for a, b in pairwise(ordered)]
        if not spacings:
            continue
        typical = _median_low(spacings)
        windows: list[Window] = []
        for a, b in pairwise(ordered):
            gap = b.observed_at - a.observed_at
            if gap > 2 * typical:
                continue  # a collection gap: when those replies happened is unknown
            delta = b.raw_value - a.raw_value
            if delta < 0:
                continue  # a source correction, not negative attention
            windows.append(Window(a.observed_at, b.observed_at, delta))
        if windows:
            series[key] = windows
    return series


def mention_series(state: InformationState) -> dict[SeriesKey, tuple[Window, ...]]:
    """Every discrete-mention series visible in ``state``, keyed by
    (source, subject), each sorted by window start."""

    def build() -> dict[SeriesKey, tuple[Window, ...]]:
        rows = _by_metric(state)
        series = _window_counts(
            rows.get(Metric.MENTIONS, ()), Metric.MENTIONS, ATTENTION_SOURCES
        )
        for key, windows in _cumulative_deltas(rows.get(Metric.REPLIES_TOTAL, ())).items():
            series.setdefault(key, []).extend(windows)
            series[key].sort(key=lambda w: (w.start, w.end))
        return {k: tuple(series[k]) for k in sorted(series, key=lambda k: (k[0].value, k[1]))}

    return dict(_memoised(state, "mention_series", build))


def _resolution(windows: Sequence[Window]) -> timedelta:
    return _median_low([w.end - w.start for w in windows])


def _inside(windows: Sequence[Window], start: datetime, end: datetime) -> list[Window]:
    """Windows fully inside [start, end]. ``windows`` is sorted by start, so
    the scan begins at the first candidate and stops at the first window
    starting at or after ``end`` (it cannot fit)."""
    out: list[Window] = []
    for i in range(bisect_left(windows, start, key=_start_of), len(windows)):
        w = windows[i]
        if w.start >= end:
            break
        if w.end <= end:
            out.append(w)
    return out


def _start_of(w: Window) -> datetime:
    return w.start


def _count(windows: Sequence[Window], start: datetime, end: datetime) -> Decimal:
    return sum((w.value for w in _inside(windows, start, end)), Decimal(0))


def _merge(windows: Iterable[Window]) -> list[tuple[datetime, datetime]]:
    """Union of the windows as disjoint [start, end) intervals. Touching
    windows merge — consecutive readings tile time without a gap."""
    merged: list[tuple[datetime, datetime]] = []
    for w in sorted(windows, key=lambda w: (w.start, w.end)):
        if merged and w.start <= merged[-1][1]:
            if w.end > merged[-1][1]:
                merged[-1] = (merged[-1][0], w.end)
        else:
            merged.append((w.start, w.end))
    return merged


def _union_length(windows: Iterable[Window]) -> timedelta:
    return sum((end - start for start, end in _merge(windows)), timedelta(0))


# --------------------------------------------------------------------------
# Source status
# --------------------------------------------------------------------------


def source_status(state: InformationState) -> dict[Source, SourceAvailability]:
    by_source = {s.source: s for s in state.sources}
    return {
        source: by_source.get(
            source,
            SourceAvailability(source, SourceStatus.UNAVAILABLE, "never_collected", None),
        )
        for source in sorted(Source, key=lambda s: s.value)
    }


def _reason(availability: SourceAvailability) -> str:
    return availability.reason or availability.status.value


def _no_available_reason(status: dict[Source, SourceAvailability]) -> str:
    parts = [f"{s.value}={_reason(status[s])}" for s in ATTENTION_ORDER]
    return "no_available_source:" + ";".join(parts)


# --------------------------------------------------------------------------
# Features
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LiveSeries:
    """A series that may speak for "now": its source is AVAILABLE and its
    newest window ended within its source's freshness budget of as_of
    (``state.source_max_age``, as applied by the gate).

    ``anchor`` is where "now" is for this series — its newest window end, never
    later than as_of. GDELT publishes a 15-minute bucket about 15 minutes after
    it closes; counting (as_of - 1h, as_of] would always miss the last bucket or
    two and read publication lag as a falling rate. Reading each series up to
    its own latest complete window removes that bias without pro-rating, and
    is no look-ahead: every window was already admitted by the gate.
    """

    windows: tuple[Window, ...]
    anchor: datetime
    resolution: timedelta
    first_start: datetime


def _live(
    series: dict[SeriesKey, tuple[Window, ...]],
    available: Iterable[Source],
    as_of: datetime,
    budgets: Mapping[Source, timedelta],
) -> dict[SeriesKey, LiveSeries]:
    sources = frozenset(available)
    live: dict[SeriesKey, LiveSeries] = {}
    for key, windows in series.items():
        if key[0] not in sources:
            continue
        done = [w for w in windows if w.end <= as_of]
        if not done:
            continue
        newest = max(w.end for w in done)
        if as_of - newest > budgets[key[0]]:
            continue  # behind by more than the freshness budget: not "now"
        live[key] = LiveSeries(
            windows=tuple(done),
            anchor=newest,
            resolution=_resolution(done),
            first_start=done[0].start,
        )
    return live


def _mentions_over(live: dict[SeriesKey, LiveSeries], span: timedelta) -> Measured:
    if not live:
        return Unavailable(NO_RECENT_OBSERVATION)
    cover = [s for s in live.values() if s.resolution <= span]
    if not cover:
        return Unavailable(NO_SOURCE_AT_RESOLUTION)
    return sum((_count(s.windows, s.anchor - span, s.anchor) for s in cover), Decimal(0))


def _hourly_counts(
    live: dict[SeriesKey, LiveSeries], hours: int
) -> list[Decimal] | Unavailable:
    """Mentions in each of the trailing ``hours`` hours (newest first), over the
    series observed since the start of the oldest hour compared."""
    if not live:
        return Unavailable(NO_RECENT_OBSERVATION)
    hourly = [s for s in live.values() if s.resolution <= HOUR]
    if not hourly:
        return Unavailable(NO_SOURCE_AT_RESOLUTION)
    eligible = [s for s in hourly if s.first_start <= s.anchor - hours * HOUR]
    if not eligible:
        return Unavailable(INSUFFICIENT_HISTORY)
    return [
        sum(
            (
                _count(s.windows, s.anchor - (i + 1) * HOUR, s.anchor - i * HOUR)
                for s in eligible
            ),
            Decimal(0),
        )
        for i in range(hours)
    ]


def _velocity(live: dict[SeriesKey, LiveSeries]) -> Measured:
    counts = _hourly_counts(live, 2)
    if isinstance(counts, Unavailable):
        return counts
    return ratio(counts[0], counts[1])


def _acceleration(live: dict[SeriesKey, LiveSeries]) -> Measured:
    counts = _hourly_counts(live, 3)
    if isinstance(counts, Unavailable):
        return counts
    now = ratio(counts[0], counts[1])
    before = ratio(counts[1], counts[2])
    if isinstance(now, Unavailable):
        return now
    if isinstance(before, Unavailable):
        return before
    return now - before


def _baseline_multiple(live: dict[SeriesKey, LiveSeries], cfg: AttentionConfig) -> Measured:
    if not live:
        return Unavailable(NO_RECENT_OBSERVATION)
    hourly = [s for s in live.values() if s.resolution <= HOUR]
    if not hourly:
        return Unavailable(NO_SOURCE_AT_RESOLUTION)
    rate = Decimal(0)
    total = Decimal(0)
    for s in hourly:
        counted = _inside(
            s.windows, s.anchor - cfg.baseline_window, s.anchor - cfg.baseline_gap
        )
        observed = _union_length(counted)
        if observed <= timedelta(0):
            continue
        mentions = sum((w.value for w in counted), Decimal(0))
        total += mentions
        rate += mentions / _hours(observed)
    if total < cfg.min_baseline_mentions:
        # 3 mentions over a week is not a baseline; 3 / 0.1 is not "30x".
        return Unavailable(INSUFFICIENT_BASELINE)
    now = sum((_count(s.windows, s.anchor - HOUR, s.anchor) for s in hourly), Decimal(0))
    return ratio(now, rate)


def _latest_metric(
    state: InformationState, metric: Metric, status: dict[Source, SourceAvailability]
) -> Measured:
    """Most recent window of ``metric`` per AVAILABLE source, summed across
    sources (different platforms are different accounts). Windows are not
    summed over time: distinct participants per hour do not add up to distinct
    participants per day."""
    series = _window_counts(_by_metric(state).get(metric, ()), metric, ATTENTION_SOURCES)
    if not series:
        return Unavailable(NO_SOURCE)
    as_of = state.as_of
    total: Decimal | None = None
    any_available = False
    for (source, _subject), windows in series.items():
        if status[source].status is not SourceStatus.AVAILABLE:
            continue
        any_available = True
        recent = [w for w in windows if as_of - DAY < w.end <= as_of]
        if recent:
            latest = max(recent, key=lambda w: (w.end, w.start))
            total = (total or Decimal(0)) + latest.value
    if not any_available:
        return Unavailable("source_not_available")
    if total is None:
        return Unavailable("no_recent_reading")
    return total


def _wikipedia(
    state: InformationState, status: dict[Source, SourceAvailability], cfg: AttentionConfig
) -> dict[str, Measured]:
    availability = status[Source.WIKIPEDIA]
    if availability.status is not SourceStatus.AVAILABLE:
        reason = Unavailable(_reason(availability))
        return {"daily_views": reason, "views_baseline_multiple": reason}
    series = _window_counts(
        _by_metric(state).get(Metric.PAGEVIEWS, ()),
        Metric.PAGEVIEWS,
        frozenset({Source.WIKIPEDIA}),
    )
    # Several articles for one meme are several pages: sum per window.
    per_window: dict[tuple[datetime, datetime], Decimal] = {}
    for windows in series.values():
        for w in windows:
            if w.end <= state.as_of:
                slot = (w.start, w.end)
                per_window[slot] = per_window.get(slot, Decimal(0)) + w.value
    if not per_window:
        missing = Unavailable("no_pageviews")
        return {"daily_views": missing, "views_baseline_multiple": missing}
    latest_slot = max(per_window, key=lambda s: (s[1], s[0]))
    latest = per_window[latest_slot]
    prior = [
        v
        for (start, end), v in per_window.items()
        if end <= latest_slot[0] and start >= latest_slot[0] - cfg.baseline_window
    ]
    multiple: Measured
    if not prior:
        multiple = Unavailable(INSUFFICIENT_BASELINE)
    else:
        multiple = ratio(latest, sum(prior, Decimal(0)) / Decimal(len(prior)))
    return {"daily_views": latest, "views_baseline_multiple": multiple}


def _active_last_day(
    state: InformationState, source: Source, series: dict[SeriesKey, tuple[Window, ...]]
) -> bool:
    """Nonzero activity of any kind ending in (as_of - 24h, as_of]. A presence
    test, not a count, so a straddling window counts here."""
    as_of = state.as_of
    for (src, _subject), windows in series.items():
        if src is source and any(
            w.value > 0 and as_of - DAY < w.end <= as_of for w in reversed(windows)
        ):
            return True
    rows = _by_metric(state)
    for metric in sorted(_ACTIVITY_METRICS):
        for obs in rows.get(metric, ()):
            if (
                obs.source is source
                and obs.value_kind is ValueKind.WINDOW_COUNT
                and obs.window_end is not None
                and as_of - DAY < obs.window_end <= as_of
                and obs.raw_value > 0
            ):
                return True
    return False


def _budgets(state: InformationState, cfg: AttentionConfig) -> dict[Source, timedelta]:
    """The gate's per-source budgets; for a hand-built state without them,
    the same defaults the gate would have applied."""
    if state.source_max_age:
        applied = dict(state.source_max_age)
        return {s: applied.get(s, cfg.max_observation_age) for s in Source}
    return freshness_budgets(None, cfg.max_observation_age)


def attention_features(state: InformationState, cfg: AttentionConfig) -> AttentionFeatures:
    """Attention at ``state.as_of``. See the module docstring for definitions."""
    budgets = _budgets(state, cfg)
    as_of = state.as_of
    status = source_status(state)
    series = mention_series(state)
    available = [s for s in ATTENTION_ORDER if status[s].status is SourceStatus.AVAILABLE]

    per_source: dict[str, dict[str, Measured]] = {}
    for source in ATTENTION_ORDER:
        if source is Source.WIKIPEDIA:
            per_source[source.value] = _wikipedia(state, status, cfg)
            continue
        if status[source].status is not SourceStatus.AVAILABLE:
            reason = Unavailable(_reason(status[source]))
            per_source[source.value] = {"mentions_1h": reason, "mentions_24h": reason}
            continue
        own = _live(
            {k: w for k, w in series.items() if k[0] is source},
            [source],
            as_of,
            budgets,
        )
        per_source[source.value] = {
            "mentions_1h": _mentions_over(own, HOUR),
            "mentions_24h": _mentions_over(own, DAY),
        }

    if not available:
        none = Unavailable(_no_available_reason(status))
        return AttentionFeatures(
            as_of=as_of,
            meme_id=state.meme.id,
            mentions_5m=none,
            mentions_15m=none,
            mentions_1h=none,
            mentions_6h=none,
            mentions_24h=none,
            velocity=none,
            acceleration=none,
            baseline_multiple=none,
            unique_participants=none,
            engagement=none,
            platform_count=none,
            per_source=per_source,
            contains_backfill=state.contains_backfill,
        )

    live = _live(series, available, as_of, budgets)
    mentions = {name: _mentions_over(live, span) for name, span in MENTION_WINDOWS}
    platforms = sum(1 for s in available if _active_last_day(state, s, series))

    return AttentionFeatures(
        as_of=as_of,
        meme_id=state.meme.id,
        mentions_5m=mentions["mentions_5m"],
        mentions_15m=mentions["mentions_15m"],
        mentions_1h=mentions["mentions_1h"],
        mentions_6h=mentions["mentions_6h"],
        mentions_24h=mentions["mentions_24h"],
        velocity=_velocity(live),
        acceleration=_acceleration(live),
        baseline_multiple=_baseline_multiple(live, cfg),
        unique_participants=_latest_metric(state, Metric.UNIQUE_PARTICIPANTS, status),
        engagement=_latest_metric(state, Metric.ENGAGEMENT, status),
        platform_count=Decimal(platforms),
        per_source=per_source,
        contains_backfill=state.contains_backfill,
    )


def attention_series(
    state: InformationState, *, bucket: timedelta, until: datetime | None = None
) -> list[tuple[datetime, Measured]]:
    """Discrete-mention rate per hour in each complete, epoch-aligned bucket.

    Each entry is ``(bucket_start, rate)``. A bucket is Measured only from
    series that (a) resolve finer than the bucket and (b) observed it
    *continuously* — the union of their windows covers the whole bucket.
    Otherwise it is ``Unavailable("not_observed")``: an hour nobody was
    watching is not a quiet hour. Windows straddling a bucket edge are not
    split (never pro-rate), so a series sampled off the hour slightly
    undercounts each bucket; the bias is the same every hour and cancels in
    ratios.

    Status at ``as_of`` is deliberately not consulted: history is what was
    observed then. ``until`` never extends past ``state.as_of``.

    Linear in the visible windows: each window and each covered interval is
    placed by index arithmetic, and the result is memoised per state.
    """
    if bucket <= timedelta(0):
        raise ValueError("bucket must be positive")
    limit = state.as_of if until is None or until > state.as_of else until
    tag = f"series:{_micros(bucket)}:{limit.isoformat()}"
    return list(_memoised(state, tag, lambda: _build_series(state, bucket, limit)))


def _build_series(
    state: InformationState, bucket: timedelta, limit: datetime
) -> tuple[tuple[datetime, Measured], ...]:
    eligible = [w for w in mention_series(state).values() if w and _resolution(w) <= bucket]
    if not eligible:
        return ()
    first = _floor(min(w[0].start for w in eligible), bucket)
    n = (_floor(limit, bucket) - first) // bucket
    if n <= 0:
        return ()

    totals = [Decimal(0)] * n
    covered = [False] * n
    for windows in eligible:
        counts = [Decimal(0)] * n
        for w in windows:
            i = (w.start - first) // bucket
            if 0 <= i < n and w.end <= first + (i + 1) * bucket:
                counts[i] += w.value
        mask = [False] * n
        for start, end in _merge(windows):
            lo = max(-((first - start) // bucket), 0)  # first bucket starting >= start
            hi = min((end - first) // bucket, n)  # buckets ending <= end
            for i in range(lo, hi):
                mask[i] = True
        for i in range(n):
            if mask[i]:
                covered[i] = True
                totals[i] += counts[i]

    scale = Decimal(_micros(HOUR)) / Decimal(_micros(bucket))
    return tuple(
        (first + i * bucket, totals[i] * scale if covered[i] else Unavailable(NOT_OBSERVED))
        for i in range(n)
    )
