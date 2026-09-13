"""When the market is open — the rule the planner, the gap check and the
expected-count check all share.

Every case here is a real instant from the dataset's window, and the summer
ones are the point: the week's boundary is 17:00 New York, which is 21:00 UTC
under daylight saving and 22:00 UTC outside it. A UTC constant is wrong for
roughly thirty weekends a year.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.labs.forex_lab import market

WINTER_FRI = datetime(2020, 1, 3, tzinfo=UTC)   # EST: boundary at 22:00 UTC
SUMMER_FRI = datetime(2020, 6, 5, tzinfo=UTC)   # EDT: boundary at 21:00 UTC


def at(day: datetime, hour: int) -> datetime:
    return day.replace(hour=hour)


def test_the_week_closes_at_22_utc_in_winter():
    assert market.is_open(at(WINTER_FRI, 21)) is True
    assert market.is_open(at(WINTER_FRI, 22)) is False


def test_the_week_closes_at_21_utc_in_summer():
    """The bug this module exists for. Under daylight saving, 17:00 New York is
    21:00 UTC — an hour earlier than the winter close."""
    assert market.is_open(at(SUMMER_FRI, 20)) is True
    assert market.is_open(at(SUMMER_FRI, 21)) is False
    assert market.is_open(at(SUMMER_FRI, 22)) is False


def test_sunday_opens_at_21_utc_in_summer_and_22_in_winter():
    """The other face of the same bug, and the expensive one: a planner that
    skips Sunday 21:00 UTC in summer loses an hour of genuinely open market on
    every summer weekend."""
    summer_sun = datetime(2020, 6, 7, tzinfo=UTC)
    assert market.is_open(at(summer_sun, 20)) is False
    assert market.is_open(at(summer_sun, 21)) is True

    winter_sun = datetime(2020, 1, 5, tzinfo=UTC)
    assert market.is_open(at(winter_sun, 21)) is False
    assert market.is_open(at(winter_sun, 22)) is True


def test_saturday_is_never_open():
    for h in range(24):
        assert market.is_open(at(datetime(2020, 6, 6, tzinfo=UTC), h)) is False
        assert market.is_open(at(datetime(2020, 1, 4, tzinfo=UTC), h)) is False


def test_midweek_is_always_open():
    for day in (datetime(2020, 6, 8, tzinfo=UTC), datetime(2023, 11, 15, tzinfo=UTC)):
        for h in range(24):
            assert market.is_open(at(day, h)) is True


def test_the_dst_switch_weekends_themselves():
    """US DST began 8 March 2020 and ended 1 November 2020. The Friday before
    each switch and the Sunday of it fall on opposite sides of the boundary."""
    assert market.is_open(datetime(2020, 3, 6, 21, tzinfo=UTC)) is True   # still EST
    assert market.is_open(datetime(2020, 3, 6, 22, tzinfo=UTC)) is False
    assert market.is_open(datetime(2020, 3, 8, 21, tzinfo=UTC)) is True   # now EDT
    assert market.is_open(datetime(2020, 10, 30, 20, tzinfo=UTC)) is True  # still EDT
    assert market.is_open(datetime(2020, 10, 30, 21, tzinfo=UTC)) is False
    assert market.is_open(datetime(2020, 11, 1, 21, tzinfo=UTC)) is False  # now EST
    assert market.is_open(datetime(2020, 11, 1, 22, tzinfo=UTC)) is True


def test_a_full_week_is_exactly_one_hundred_and_twenty_hours():
    """Sunday 17:00 New York to Friday 17:00 New York, five days, however the
    UTC offset moves underneath it."""
    for start in (datetime(2020, 1, 5, tzinfo=UTC), datetime(2020, 6, 7, tzinfo=UTC),
                  datetime(2023, 9, 10, tzinfo=UTC)):
        hours = list(market.open_hours(start, start.replace() + __import__(
            "datetime").timedelta(days=7)))
        assert len(hours) == 120, f"{start:%Y-%m-%d}: {len(hours)}"


def test_the_expected_minute_count_matches_what_2020_actually_loaded():
    """2020 loaded 371,658 candles. The model must land within the integrity
    check's own 5% of that, or a correct dataset fails its own check."""
    expected = market.open_minutes_in_year(2020, date(2020, 1, 1), date(2026, 6, 30))
    assert abs(1 - 371_658 / expected) < 0.05, expected


def test_2026_is_counted_to_june_only():
    full = market.open_minutes_in_year(2025, date(2020, 1, 1), date(2026, 6, 30))
    half = market.open_minutes_in_year(2026, date(2020, 1, 1), date(2026, 6, 30))
    assert 0.45 < half / full < 0.55


# --- holidays -----------------------------------------------------------------


def test_easter_is_computed_not_guessed():
    """The first version of the holiday check asked whether a gap ran
    Thursday-to-Monday in March or April. That misses Good Friday 2020 — a
    Friday-to-Sunday gap, and the single unexplained gap in the whole of 2020
    before this was written."""
    assert market.easter_sunday(2020) == date(2020, 4, 12)
    assert market.easter_sunday(2021) == date(2021, 4, 4)
    assert market.easter_sunday(2022) == date(2022, 4, 17)
    assert market.easter_sunday(2023) == date(2023, 4, 9)
    assert market.easter_sunday(2024) == date(2024, 3, 31)
    assert market.easter_sunday(2025) == date(2025, 4, 20)
    assert market.easter_sunday(2026) == date(2026, 4, 5)


def test_good_friday_2020_explains_the_gap_it_actually_opened():
    """2020-04-10 20:58 UTC to 2020-04-12 22:00 UTC, the one real hole the
    DST fix left behind."""
    a = datetime(2020, 4, 10, 20, 58, tzinfo=UTC)
    b = datetime(2020, 4, 12, 22, 0, tzinfo=UTC)
    assert market.holiday_name(a, b) == "Good Friday"


def test_either_end_of_a_gap_can_carry_the_holiday():
    assert market.holiday_name(datetime(2023, 12, 24, 12, tzinfo=UTC),
                               datetime(2023, 12, 27, 2, tzinfo=UTC)) == "Christmas Eve"
    assert market.holiday_name(datetime(2023, 12, 23, 12, tzinfo=UTC),
                               datetime(2023, 12, 25, 2, tzinfo=UTC)) == "Christmas Day"


def test_an_ordinary_weekday_gap_is_not_excused():
    """The check is only worth running if it can still say no."""
    assert market.holiday_name(datetime(2023, 5, 17, 3, tzinfo=UTC),
                               datetime(2023, 5, 17, 9, tzinfo=UTC)) is None
