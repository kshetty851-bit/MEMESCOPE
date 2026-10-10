"""Candle validation, gap reporting and resampling. Pure.

Nothing here repairs data. A bar that is wrong is counted, a bar that is
missing is reported as a gap, and a resampled bucket built from fewer source
bars than it should have is counted as incomplete — never padded, interpolated
or forward-filled. A strategy tested on invented prices is a strategy tested
on nothing.

The weekend model is `sessions.is_weekend_closed` (Fri 21:00 to Sun 22:00 UTC).
Bars inside that window are not *expected*, so their absence is not a defect.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise

from app.labs.forex.sessions import is_weekend_closed
from app.labs.forex.types import TIMEFRAME_SECONDS, Candle, Timeframe

MAX_REPORTED_GAPS = 50
GRADE_GOOD_COVERAGE = 99.5
GRADE_FAIR_COVERAGE = 97.0

NOTE_WEEKEND_MODEL = "weekend_closure_model_fri21_sun22_utc"
NOTE_HOLIDAY_NOT_MISSING = "holiday_gaps_not_counted_as_missing"
NOTE_GAPS_TRUNCATED = "gaps_truncated_to_largest_50"
NOTE_NAIVE_AS_UTC = "naive_datetimes_assumed_utc"
NOTE_UNSORTED = "input_not_sorted"

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

KIND_WEEKEND = "weekend"
KIND_HOLIDAY = "holiday"
KIND_MISSING = "missing"


@dataclass(frozen=True)
class Gap:
    """A run of absent bars. `start`/`end` are the first and last absent
    open_time, both inclusive."""

    start: datetime
    end: datetime
    missing_bars: int
    kind: str


@dataclass(frozen=True)
class QualityReport:
    symbol: str
    timeframe: Timeframe
    bars: int
    start: datetime | None
    end: datetime | None
    duplicates: int
    misaligned: int
    non_utc: int
    ohlc_violations: int
    out_of_order: int
    expected_bars: int
    missing_bars: int
    coverage_pct: float
    gaps: tuple[Gap, ...]
    gap_count: int
    largest_gap_bars: int
    grade: str
    notes: tuple[str, ...]


@dataclass(frozen=True)
class ResampleResult:
    candles: tuple[Candle, ...]
    incomplete_buckets: int
    #: Repeated source open_times skipped (first kept) so volume is not double-counted.
    duplicates_dropped: int = 0


def _floor(dt: datetime, step: int) -> datetime:
    """Largest multiple of `step` seconds since the epoch that is <= dt.

    Every supported timeframe divides 86,400, so epoch alignment is the same
    as alignment from 00:00 UTC.
    """
    n = (dt - _EPOCH) // timedelta(seconds=step)
    return _EPOCH + timedelta(seconds=n * step)


def _ceil(dt: datetime, step: int) -> datetime:
    f = _floor(dt, step)
    return f if f == dt else f + timedelta(seconds=step)


def _to_utc(dt: datetime) -> tuple[datetime, bool, bool]:
    """(utc_datetime, is_naive, is_non_utc). Naive values are assumed UTC for
    analysis only, and counted so the caller can see it happened."""
    offset = dt.utcoffset()
    if dt.tzinfo is None or offset is None:
        return dt.replace(tzinfo=UTC), True, True
    return dt.astimezone(UTC), False, offset != timedelta(0)


def _ohlc_bad(c: Candle) -> bool:
    prices = (c.open, c.high, c.low, c.close)
    if any(not math.isfinite(p) or p <= 0 for p in prices):
        return True
    return c.high < c.low or c.high < max(c.open, c.close) or c.low > min(c.open, c.close)


def _next_edge(t: datetime, closed: bool) -> datetime:
    """First instant after `t` at which the market state flips."""
    wd = t.weekday()
    if closed:
        d = t.date() + timedelta(days=6 - wd)
        return datetime(d.year, d.month, d.day, 22, tzinfo=UTC)
    d = t.date() + timedelta(days=(4 - wd) % 7)
    return datetime(d.year, d.month, d.day, 21, tzinfo=UTC)


def _runs(first: datetime, last: datetime, step: int) -> list[tuple[datetime, datetime, bool]]:
    """Split the aligned bars first..last (inclusive) into maximal runs that are
    all open or all weekend-closed. Walks edges, not bars, so a gap of years
    costs a loop per week instead of per minute."""
    out: list[tuple[datetime, datetime, bool]] = []
    delta = timedelta(seconds=step)
    t = first
    while t <= last:
        closed = is_weekend_closed(t)
        end = min(last, _next_edge(t, closed) - delta)
        out.append((t, end, closed))
        t = end + delta
    return out


def _bar_count(a: datetime, b: datetime, step: int) -> int:
    return int((b - a).total_seconds() // step) + 1


def _touches_holiday(start: datetime, end: datetime) -> bool:
    for year in range(start.year, end.year + 1):
        for d in (date(year, 12, 25), date(year, 1, 1)):
            if start.date() <= d <= end.date():
                return True
    return False


def _classify(start: datetime, end: datetime, closed: bool) -> str:
    if closed:
        return KIND_WEEKEND
    return KIND_HOLIDAY if _touches_holiday(start, end) else KIND_MISSING


def _find_gaps(times: Sequence[datetime], step: int) -> list[Gap]:
    gaps: list[Gap] = []
    delta = timedelta(seconds=step)
    for prev, cur in pairwise(times):
        if cur - prev <= delta:
            continue
        for start, end, closed in _runs(prev + delta, cur - delta, step):
            gaps.append(
                Gap(start, end, _bar_count(start, end, step), _classify(start, end, closed))
            )
    return gaps


def _grade(
    bars: int, coverage: float, ohlc: int, dups: int, misaligned: int, non_utc: int
) -> str:
    if bars == 0:
        return "empty"
    if coverage >= GRADE_GOOD_COVERAGE and not (ohlc or dups or misaligned or non_utc):
        return "good"
    if coverage >= GRADE_FAIR_COVERAGE and ohlc == 0:
        return "fair"
    return "poor"


def validate(candles: Sequence[Candle], symbol: str, timeframe: Timeframe) -> QualityReport:
    step = TIMEFRAME_SECONDS[timeframe]
    if not candles:
        return QualityReport(
            symbol, timeframe, 0, None, None, 0, 0, 0, 0, 0, 0, 0, 100.0, (), 0, 0, "empty",
            (NOTE_WEEKEND_MODEL,),
        )  # fmt: skip

    seen: set[datetime] = set()
    aligned: list[datetime] = []
    dups = misaligned = non_utc = ohlc = out_of_order = naive = 0
    prev: datetime | None = None
    lo: datetime | None = None
    hi: datetime | None = None
    for c in candles:
        t, is_naive, is_non_utc = _to_utc(c.open_time)
        naive += is_naive
        non_utc += is_non_utc
        ohlc += _ohlc_bad(c)
        if prev is not None and t < prev:
            out_of_order += 1
        prev = t
        lo = t if lo is None or t < lo else lo
        hi = t if hi is None or t > hi else hi
        is_dup = t in seen
        dups += is_dup
        seen.add(t)
        if t != _floor(t, step):
            misaligned += 1
        elif not is_dup:
            aligned.append(t)
    aligned.sort()

    gaps = _find_gaps(aligned, step)
    expected = 0
    if aligned:
        # Judged over the aligned span: a misaligned straggler at either end
        # has no grid slot, so it cannot define bars that "should" exist.
        expected = sum(
            _bar_count(a, b, step)
            for a, b, closed in _runs(aligned[0], aligned[-1], step)
            if not closed
        )
    missing = sum(g.missing_bars for g in gaps if g.kind == KIND_MISSING)
    coverage = (expected - missing) / expected * 100.0 if expected else 100.0

    # Real defects first: with ~100 weekend gaps a year, ranking by size alone
    # would push every genuine hole out of the reported list.
    ranked = sorted(gaps, key=lambda g: (g.kind == KIND_WEEKEND, -g.missing_bars, g.start))
    reported = tuple(ranked[:MAX_REPORTED_GAPS])
    largest = max((g.missing_bars for g in gaps if g.kind == KIND_MISSING), default=0)

    notes = [NOTE_WEEKEND_MODEL]
    if any(g.kind == KIND_HOLIDAY for g in gaps):
        notes.append(NOTE_HOLIDAY_NOT_MISSING)
    if len(gaps) > MAX_REPORTED_GAPS:
        notes.append(NOTE_GAPS_TRUNCATED)
    if naive:
        notes.append(NOTE_NAIVE_AS_UTC)
    if out_of_order:
        notes.append(NOTE_UNSORTED)

    return QualityReport(
        symbol=symbol,
        timeframe=timeframe,
        bars=len(candles),
        start=lo,
        end=hi,
        duplicates=dups,
        misaligned=misaligned,
        non_utc=non_utc,
        ohlc_violations=ohlc,
        out_of_order=out_of_order,
        expected_bars=expected,
        missing_bars=missing,
        coverage_pct=coverage,
        gaps=reported,
        gap_count=len(gaps),
        largest_gap_bars=largest,
        grade=_grade(len(candles), coverage, ohlc, dups, misaligned, non_utc),
        notes=tuple(notes),
    )


def resample(
    candles: Sequence[Candle], source: Timeframe, target: Timeframe
) -> ResampleResult:
    s, t = TIMEFRAME_SECONDS[source], TIMEFRAME_SECONDS[target]
    if t % s != 0:
        raise ValueError(f"{target.value} is not a multiple of {source.value}")
    if source == target:
        return ResampleResult(tuple(candles), 0)
    if any(c.open_time.tzinfo is None for c in candles):
        raise ValueError("candles must carry tz-aware open_time")

    per_bucket = t // s
    out: list[Candle] = []
    incomplete = dropped = 0
    cur: datetime | None = None
    o = h = lo = c_ = v = 0.0
    count = 0
    last_seen: datetime | None = None

    def flush() -> None:
        nonlocal incomplete
        if cur is None:
            return
        out.append(Candle(cur, o, h, lo, c_, v))
        if count < per_bucket:
            incomplete += 1

    for c in sorted(candles, key=lambda x: x.open_time):
        if last_seen is not None and c.open_time == last_seen:
            dropped += 1
            continue
        last_seen = c.open_time
        bucket = _floor(c.open_time.astimezone(UTC), t)
        if bucket != cur:
            flush()
            cur, o, h, lo, c_, v, count = bucket, c.open, c.high, c.low, c.close, c.volume, 1
        else:
            h, lo, c_ = max(h, c.high), min(lo, c.low), c.close
            v += c.volume
            count += 1
    flush()
    return ResampleResult(tuple(out), incomplete, dropped)


def slice_window(
    candles: Sequence[Candle], start: datetime | None, end: datetime | None
) -> tuple[Candle, ...]:
    """Candles with start <= open_time < end. `candles` must be sorted."""
    for bound in (start, end):
        if bound is not None and bound.tzinfo is None:
            raise ValueError("window bounds must be tz-aware")
    lo = 0 if start is None else bisect_left(candles, start, key=lambda c: c.open_time)
    hi = len(candles) if end is None else bisect_left(candles, end, key=lambda c: c.open_time)
    return tuple(candles[lo:hi])
