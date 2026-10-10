"""UTC session and market-hours helpers. Pure.

The FX week runs from Sunday ~21:00/22:00 UTC to Friday ~21:00/22:00 UTC; the
hour moves with US daylight saving. The lab does not model DST: it treats
Friday 21:00 UTC to Sunday 22:00 UTC as closed, which is the union of both
seasons. A bar inside that window is never *expected*, so its absence is not a
data gap — and a bar that does appear there is kept, not discarded.

Rollover (when overnight financing is charged) is 22:00 UTC, the winter value
of 17:00 New York; the one-hour summer shift is disclosed, not modelled.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.labs.forex.types import Session

ROLLOVER_HOUR_UTC = 22
#: Friday 21:00 UTC .. Sunday 22:00 UTC.
_WEEKEND_CLOSE = (4, 21)  # (weekday, hour) — Friday
_WEEKEND_OPEN = (6, 22)  # Sunday


def minute_of_day(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


def in_session(dt: datetime, session: Session) -> bool:
    """Whether `dt` falls in [start, end) of `session` on its UTC day.

    A session whose end is earlier than its start wraps midnight (e.g. 22:00 to
    02:00). A session whose start equals its end covers the whole day.
    """
    start = session.start_hour * 60 + session.start_minute
    end = session.end_hour * 60 + session.end_minute
    m = minute_of_day(dt)
    if start == end:
        return True
    if start < end:
        return start <= m < end
    return m >= start or m < end


def is_weekend_closed(dt: datetime) -> bool:
    """Whether the FX market is closed at `dt` (UTC) under the lab's model."""
    wd, hour = dt.weekday(), dt.hour
    if wd == 5:  # Saturday
        return True
    if wd == _WEEKEND_CLOSE[0] and hour >= _WEEKEND_CLOSE[1]:
        return True
    return wd == _WEEKEND_OPEN[0] and hour < _WEEKEND_OPEN[1]


def rollovers_between(start: datetime, end: datetime) -> list[datetime]:
    """Every 22:00 UTC instant in (start, end], weekends included; weight each
    with `swap_multiplier`, which charges weekend instants zero."""
    first = start.replace(hour=ROLLOVER_HOUR_UTC, minute=0, second=0, microsecond=0)
    if first <= start:
        first += timedelta(days=1)
    out: list[datetime] = []
    t = first
    while t <= end:
        out.append(t)
        t += timedelta(days=1)
    return out


def swap_multiplier(rollover: datetime) -> int:
    """How many nights a rollover at `rollover` charges.

    Brokers roll Monday to Friday and charge Wednesday triple, so a week costs
    seven nights: Mon 1, Tue 1, Wed 3, Thu 1, Fri 1. Saturday and Sunday
    instants charge nothing — those nights were paid on Wednesday.
    """
    wd = rollover.weekday()
    if wd == 2:
        return 3
    if wd in (0, 1, 3, 4):
        return 1
    return 0
