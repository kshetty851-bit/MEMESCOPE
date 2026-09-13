"""When the FX market is open. One definition, used by the planner, the gap
check and the expected-count check.

The week runs Sunday 17:00 New York to Friday 17:00 New York. In UTC that is
22:00 in winter and **21:00 in summer**, because New York observes daylight
saving and UTC does not — and writing the boundary as a UTC constant is a bug
with two faces:

* the planner skips Sunday 21:00–22:00 UTC through every summer, which is an
  hour of genuinely open market lost on ~30 weekends a year;
* the gap check reports Friday 20:59 → Sunday 22:00 as an unexplained hole on
  every one of those weekends, so a perfectly loaded dataset fails its own
  integrity check ~200 times.

Both were live. Keeping the rule in one place, expressed in the timezone the
rule is actually written in, is what stops them coming back.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
#: 17:00 New York, the week's open on Sunday and its close on Friday.
WEEK_BOUNDARY_HOUR_NY = 17


def is_open(t: datetime) -> bool:
    """Is the market open at this instant? Takes an aware UTC datetime."""
    ny = t.astimezone(NY)
    wd = ny.weekday()  # Mon=0 .. Sun=6
    shut = (
        wd == 5  # Saturday, all of it
        or (wd == 4 and ny.hour >= WEEK_BOUNDARY_HOUR_NY)  # Friday, after the close
        or (wd == 6 and ny.hour < WEEK_BOUNDARY_HOUR_NY)  # Sunday, before the open
    )
    return not shut


def open_hours(start: datetime, end: datetime):
    """Every open hour in [start, end). The boundary falls exactly on an hour
    in UTC either side of the DST switch, so an hour is wholly open or wholly
    shut and testing its first instant is exact."""
    h = start
    while h < end:
        if is_open(h):
            yield h
        h += timedelta(hours=1)


@lru_cache(maxsize=16)
def open_minutes_in_year(year: int, window_start: date, window_end: date) -> int:
    """Minutes the market was OPEN in `year`, clipped to the backtest window.

    Counted hour by hour from `is_open` rather than from an average week, so
    leap years, both DST switches and a window that stops on 30 June are all
    handled by the same predicate the loader uses.

    No holiday allowance is subtracted, deliberately. An earlier version took
    9/365 off for market holidays, which made a COMPLETE year read as 1.015 —
    above 1 — and that is the wrong shape for this check entirely. A year can
    never legitimately hold more minutes than the market was open for; it can
    only hold fewer. Deflating the denominator turns a one-sided bound into a
    two-sided fudge and hides the class of bug it would otherwise catch: a
    duplicated or spurious row pushes the ratio above 1, and against a
    denominator that is already 2.4% low it simply disappears.

    Measured on 2020, the one year loaded complete: 373,418 of 377,280 open
    minutes, 0.9898 — about 3.7 days of thin tape across Christmas, New Year
    and Good Friday. The 9-day allowance was 2.4x that.
    """
    first = max(
        datetime(year, 1, 1, tzinfo=UTC),
        datetime(window_start.year, window_start.month, window_start.day, tzinfo=UTC),
    )
    last = min(
        datetime(year + 1, 1, 1, tzinfo=UTC),
        datetime(window_end.year, window_end.month, window_end.day, tzinfo=UTC)
        + timedelta(days=1),
    )
    if last <= first:
        return 0
    return sum(1 for _ in open_hours(first, last)) * 60


# --- holidays -----------------------------------------------------------------

#: Fixed-date closures big enough to open a gap over an hour wide in EUR/USD.
#: Not a full holiday calendar — a bank holiday in one centre barely dents a
#: pair this liquid, and the integrity check's 5% tolerance is what absorbs
#: those.
FIXED_HOLIDAYS: dict[tuple[int, int], str] = {
    (1, 1): "New Year's Day",
    (12, 24): "Christmas Eve",
    (12, 25): "Christmas Day",
    (12, 26): "Boxing Day",
    (12, 31): "New Year's Eve",
    (7, 4): "US Independence Day",
}


def easter_sunday(year: int) -> date:
    """The anonymous Gregorian algorithm.

    Computed rather than guessed at. The first version of this check asked
    whether a gap ran Thursday-to-Monday in March or April, which misses Good
    Friday 2020 — a Friday-to-Sunday gap — and would happily label an ordinary
    Easter-week outage as a holiday in a year where it was not one.
    """
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month, day = divmod(h + ell - 7 * m + 114, 31)
    return date(year, month, day + 1)


@lru_cache(maxsize=32)
def _easter_window(year: int) -> dict[date, str]:
    e = easter_sunday(year)
    return {
        e - timedelta(days=2): "Good Friday",
        e: "Easter Sunday",
        e + timedelta(days=1): "Easter Monday",
    }


def holiday_name(a: datetime, b: datetime) -> str | None:
    """The closure that explains a gap from `a` to `b`, if one does.

    Either END may carry it: a gap that STARTS on Christmas Eve and one that
    ENDS on Boxing Day are both Christmas.
    """
    for t in (a, b):
        d = t.date()
        name = FIXED_HOLIDAYS.get((d.month, d.day))
        if name:
            return name
        name = _easter_window(d.year).get(d)
        if name:
            return name
    return None
