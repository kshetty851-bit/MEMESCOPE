"""Quality reporting, resampling and windowing of candles.

The shared property: data is reported on, never repaired. A hole is a gap, a
short bucket is counted as incomplete, a bad bar is a violation — and no price
in any output was not in the input.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.labs.forex.data import (
    MAX_REPORTED_GAPS,
    Gap,
    resample,
    slice_window,
    validate,
)
from app.labs.forex.sessions import is_weekend_closed
from app.labs.forex.types import TIMEFRAME_SECONDS, Candle, Timeframe

pytestmark = pytest.mark.unit

# 2024-01-08 is a Monday, so Mon-Thu are plain trading days and Fri 21:00 starts the weekend.
MON = datetime(2024, 1, 8, tzinfo=UTC)


def bar(t: datetime, i: int = 0, volume: float = 10.0) -> Candle:
    base = 1.1 + 0.0001 * (i % 7)
    return Candle(t, base, base + 0.0002, base - 0.0002, base + 0.0001, volume)


def series(
    start: datetime, n: int, tf: Timeframe, *, skip: set[int] | None = None
) -> list[Candle]:
    step = timedelta(seconds=TIMEFRAME_SECONDS[tf])
    return [bar(start + step * i, i) for i in range(n) if i not in (skip or set())]


def open_market_series(start: datetime, end: datetime, tf: Timeframe) -> list[Candle]:
    """Every bar in [start, end) the weekend model says is open — a perfect feed."""
    step = timedelta(seconds=TIMEFRAME_SECONDS[tf])
    out, t, i = [], start, 0
    while t < end:
        if not is_weekend_closed(t):
            out.append(bar(t, i))
        t += step
        i += 1
    return out


class TestValidateClean:
    def test_empty_input_is_graded_empty_not_good(self) -> None:
        """No bars must never read as a clean dataset."""
        r = validate([], "EURUSD", Timeframe.M5)
        assert (r.grade, r.bars, r.start, r.end, r.expected_bars) == (
            "empty",
            0,
            None,
            None,
            0,
        )

    def test_contiguous_series_is_good_with_full_coverage(self) -> None:
        r = validate(series(MON, 288, Timeframe.M5), "EURUSD", Timeframe.M5)
        assert r.grade == "good"
        assert r.coverage_pct == 100.0
        assert (r.expected_bars, r.missing_bars, r.gap_count) == (288, 0, 0)
        assert r.start == MON
        assert r.end == MON + timedelta(minutes=5 * 287)

    def test_notes_always_name_the_weekend_model(self) -> None:
        """The closure model is an assumption; the report has to disclose it."""
        r = validate(series(MON, 10, Timeframe.M5), "EURUSD", Timeframe.M5)
        assert "weekend_closure_model_fri21_sun22_utc" in r.notes


class TestGaps:
    def test_interior_hole_is_one_missing_gap_with_exact_bounds(self) -> None:
        candles = series(MON, 100, Timeframe.H1, skip={10, 11, 12})
        r = validate(candles, "EURUSD", Timeframe.H1)
        assert r.gaps == (
            Gap(MON + timedelta(hours=10), MON + timedelta(hours=12), 3, "missing"),
        )
        assert (r.missing_bars, r.expected_bars, r.largest_gap_bars) == (3, 100, 3)
        assert r.coverage_pct == pytest.approx(97.0)
        assert r.grade == "fair"

    def test_two_missing_in_hundred_is_fair_and_none_is_good(self) -> None:
        r = validate(series(MON, 100, Timeframe.H1, skip={20, 50}), "EURUSD", Timeframe.H1)
        assert (r.coverage_pct, r.grade) == (pytest.approx(98.0), "fair")
        assert validate(series(MON, 100, Timeframe.H1), "EURUSD", Timeframe.H1).grade == "good"

    def test_heavy_loss_is_poor(self) -> None:
        r = validate(
            series(MON, 100, Timeframe.H1, skip=set(range(40, 50))), "EURUSD", Timeframe.H1
        )
        assert r.coverage_pct == pytest.approx(90.0)
        assert r.grade == "poor"

    def test_weekend_closure_is_not_a_defect(self) -> None:
        """Absence of bars while the market is closed must not cost coverage."""
        candles = open_market_series(
            MON + timedelta(days=3), MON + timedelta(days=9), Timeframe.M15
        )
        r = validate(candles, "EURUSD", Timeframe.M15)
        assert r.missing_bars == 0
        assert r.coverage_pct == 100.0
        assert r.grade == "good"
        assert [g.kind for g in r.gaps] == ["weekend"]
        # Fri 21:00 .. Sun 21:45 inclusive = 49 hours of 15-minute bars.
        assert r.gaps[0].missing_bars == 49 * 4
        assert r.gaps[0].start == datetime(2024, 1, 12, 21, tzinfo=UTC)
        assert r.gaps[0].end == datetime(2024, 1, 14, 21, 45, tzinfo=UTC)

    def test_expected_bars_matches_brute_force_count_over_weeks(self) -> None:
        """The edge-walking counter must agree with asking is_weekend_closed per bar."""
        for tf in (Timeframe.M15, Timeframe.H1):
            candles = open_market_series(MON, MON + timedelta(days=21), tf)
            r = validate(candles, "EURUSD", tf)
            assert r.expected_bars == len(candles)
            assert r.missing_bars == 0

    def test_hole_next_to_weekend_splits_into_closed_and_missing_parts(self) -> None:
        """Fri 19:00-20:00 absent and the weekend after it: only the former is a loss."""
        candles = open_market_series(
            MON + timedelta(days=4), MON + timedelta(days=7), Timeframe.H1
        )
        candles = [
            c for c in candles if c.open_time.hour not in (19, 20) or c.open_time.day != 12
        ]
        r = validate(candles, "EURUSD", Timeframe.H1)
        kinds = {g.kind: g for g in r.gaps}
        assert kinds["missing"].missing_bars == 2
        assert kinds["weekend"].missing_bars == 49
        assert r.missing_bars == 2

    def test_bars_inside_closed_window_are_kept_and_not_penalised(self) -> None:
        candles = open_market_series(
            MON + timedelta(days=4), MON + timedelta(days=7), Timeframe.H1
        )
        sat = datetime(2024, 1, 13, 12, tzinfo=UTC)
        candles = sorted([*candles, bar(sat)], key=lambda c: c.open_time)
        r = validate(candles, "EURUSD", Timeframe.H1)
        assert r.bars == len(candles)
        assert r.missing_bars == 0
        assert r.grade == "good"

    def test_christmas_gap_is_holiday_and_not_counted_missing(self) -> None:
        start = datetime(2023, 12, 22, tzinfo=UTC)  # Friday
        candles = open_market_series(
            start - timedelta(days=4), start + timedelta(days=9), Timeframe.H1
        )
        candles = [c for c in candles if c.open_time.date() != datetime(2023, 12, 25).date()]
        r = validate(candles, "EURUSD", Timeframe.H1)
        holiday = [g for g in r.gaps if g.kind == "holiday"]
        assert len(holiday) == 1
        assert holiday[0].missing_bars == 24
        assert r.missing_bars == 0
        assert "holiday_gaps_not_counted_as_missing" in r.notes

    def test_new_year_day_gap_is_holiday(self) -> None:
        candles = open_market_series(
            datetime(2023, 12, 28, tzinfo=UTC), datetime(2024, 1, 5, tzinfo=UTC), Timeframe.H1
        )
        candles = [c for c in candles if c.open_time.date() != datetime(2024, 1, 1).date()]
        r = validate(candles, "EURUSD", Timeframe.H1)
        assert [g.kind for g in r.gaps if g.kind != "weekend"] == ["holiday"]

    def test_gap_list_is_capped_but_counted_and_real_gaps_rank_before_weekends(self) -> None:
        candles = open_market_series(MON, MON + timedelta(days=35), Timeframe.H1)
        drop = {c.open_time for c in candles[::7][1:61]}  # 60 isolated one-bar holes
        candles = [c for c in candles if c.open_time not in drop]
        r = validate(candles, "EURUSD", Timeframe.H1)
        assert len(r.gaps) == MAX_REPORTED_GAPS
        assert r.gap_count > MAX_REPORTED_GAPS
        assert "gaps_truncated_to_largest_50" in r.notes
        assert all(g.kind == "missing" for g in r.gaps)
        assert r.missing_bars == 60


class TestDefects:
    def test_duplicates_are_counted_not_merged(self) -> None:
        candles = series(MON, 20, Timeframe.M5)
        r = validate([*candles, candles[3], candles[3]], "EURUSD", Timeframe.M5)
        assert r.duplicates == 2
        assert r.bars == 22
        assert r.grade == "fair"  # coverage is intact, but "good" demands zero duplicates

    def test_misaligned_by_minute_and_by_second(self) -> None:
        candles = series(MON, 10, Timeframe.M5)
        odd_minute = bar(MON + timedelta(minutes=47, hours=1))
        odd_second = bar(MON + timedelta(hours=2, seconds=1))
        r = validate([*candles, odd_minute, odd_second], "EURUSD", Timeframe.M5)
        assert r.misaligned == 2
        assert r.grade != "good"

    def test_misaligned_bar_does_not_stretch_the_expected_span(self) -> None:
        """A stray off-grid bar far away must not manufacture a huge phantom gap."""
        stray = bar(MON + timedelta(days=2, minutes=1))
        r = validate([*series(MON, 10, Timeframe.M5), stray], "EURUSD", Timeframe.M5)
        assert r.missing_bars == 0
        assert r.end == stray.open_time

    def test_non_utc_counts_naive_and_offset_aware(self) -> None:
        plus2 = timezone(timedelta(hours=2))
        candles = series(MON, 5, Timeframe.H1)
        naive = bar(datetime(2024, 1, 8, 5))
        shifted = bar(datetime(2024, 1, 8, 6, tzinfo=plus2))
        r = validate([*candles, naive, shifted], "EURUSD", Timeframe.H1)
        assert r.non_utc == 2
        assert "naive_datetimes_assumed_utc" in r.notes
        assert r.grade != "good"

    def test_utc_equivalent_offset_aware_is_not_flagged(self) -> None:
        zero = timezone(timedelta(0))
        r = validate([bar(datetime(2024, 1, 8, tzinfo=zero))], "EURUSD", Timeframe.H1)
        assert r.non_utc == 0

    def test_out_of_order_counts_each_step_backwards(self) -> None:
        c = series(MON, 6, Timeframe.M5)
        r = validate([c[0], c[2], c[1], c[3], c[5], c[4]], "EURUSD", Timeframe.M5)
        assert r.out_of_order == 2
        assert r.missing_bars == 0
        assert "input_not_sorted" in r.notes

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda c: Candle(c.open_time, c.open, c.low - 0.01, c.low, c.close),  # high < low
            lambda c: Candle(
                c.open_time, c.open, c.open - 0.00005, c.low, c.close
            ),  # high < open
            lambda c: Candle(
                c.open_time, c.open, c.high, c.close + 0.001, c.close
            ),  # low > close
            lambda c: Candle(c.open_time, 0.0, c.high, c.low, c.close),  # price <= 0
            lambda c: Candle(c.open_time, c.open, c.high, c.low, -1.0),  # negative
            lambda c: Candle(c.open_time, c.open, c.high, c.low, float("nan")),  # not a number
        ],
        ids=["high<low", "high<open", "low>close", "zero", "negative", "nan"],
    )
    def test_each_ohlc_violation_kind_is_counted_once_per_bar(self, mutate) -> None:  # type: ignore[no-untyped-def]
        candles = series(MON, 20, Timeframe.M5)
        candles[5] = mutate(candles[5])
        r = validate(candles, "EURUSD", Timeframe.M5)
        assert r.ohlc_violations == 1
        assert r.grade == "poor"  # fair and good both require zero violations

    def test_valid_flat_bar_is_not_a_violation(self) -> None:
        flat = Candle(MON, 1.1, 1.1, 1.1, 1.1)
        assert validate([flat], "EURUSD", Timeframe.M5).ohlc_violations == 0


class TestResample:
    def test_ohlcv_semantics_per_bucket(self) -> None:
        src = [
            Candle(MON + timedelta(minutes=0), 1.00, 1.05, 0.99, 1.02, 1.0),
            Candle(MON + timedelta(minutes=1), 1.02, 1.10, 1.01, 1.03, 2.0),
            Candle(MON + timedelta(minutes=2), 1.03, 1.04, 0.95, 1.01, 3.0),
            Candle(MON + timedelta(minutes=3), 1.01, 1.02, 1.00, 1.015, 4.0),
            Candle(MON + timedelta(minutes=4), 1.015, 1.03, 1.00, 1.025, 5.0),
            Candle(MON + timedelta(minutes=5), 1.025, 1.026, 1.02, 1.021, 6.0),
        ]
        r = resample(src, Timeframe.M1, Timeframe.M5)
        first, second = r.candles
        assert first == Candle(MON, 1.00, 1.10, 0.95, 1.025, 15.0)
        assert second.open_time == MON + timedelta(minutes=5)
        assert second.open == 1.025 and second.close == 1.021

    def test_short_bucket_is_emitted_and_counted_never_padded(self) -> None:
        src = series(MON, 15, Timeframe.M1, skip={7})
        r = resample(src, Timeframe.M1, Timeframe.M5)
        assert len(r.candles) == 3
        assert r.incomplete_buckets == 1
        # The incomplete bucket's volume is the sum of what existed.
        assert r.candles[1].volume == 40.0

    def test_missing_bucket_is_absent_not_synthesised(self) -> None:
        src = series(MON, 15, Timeframe.M1, skip=set(range(5, 10)))
        r = resample(src, Timeframe.M1, Timeframe.M5)
        assert [c.open_time for c in r.candles] == [MON, MON + timedelta(minutes=10)]
        assert r.incomplete_buckets == 0

    def test_single_source_bar_still_makes_an_incomplete_bucket(self) -> None:
        r = resample([bar(MON + timedelta(minutes=2))], Timeframe.M1, Timeframe.M5)
        assert len(r.candles) == 1 and r.incomplete_buckets == 1

    def test_buckets_align_to_utc_multiples_not_to_the_first_candle(self) -> None:
        src = series(MON + timedelta(minutes=5), 13, Timeframe.M5)  # 00:05 .. 01:05
        r = resample(src, Timeframe.M5, Timeframe.H1)
        assert [c.open_time for c in r.candles] == [MON, MON + timedelta(hours=1)]
        # 11 bars in the first hour and 2 in the second: both short, neither padded.
        assert r.incomplete_buckets == 2

    def test_full_hour_from_m15_is_complete(self) -> None:
        r = resample(series(MON, 8, Timeframe.M15), Timeframe.M15, Timeframe.H1)
        assert len(r.candles) == 2 and r.incomplete_buckets == 0

    def test_same_timeframe_returns_input_unchanged(self) -> None:
        src = series(MON, 5, Timeframe.M5, skip={2})
        r = resample(src, Timeframe.M5, Timeframe.M5)
        assert r.candles == tuple(src)
        assert r.incomplete_buckets == 0

    @pytest.mark.parametrize(
        ("source", "target"),
        [(Timeframe.M5, Timeframe.M1), (Timeframe.H1, Timeframe.M15)],
    )
    def test_a_target_below_the_source_is_refused(
        self, source: Timeframe, target: Timeframe
    ) -> None:
        with pytest.raises(ValueError):
            resample([], source, target)

    def test_every_supported_upsample_is_accepted(self) -> None:
        for s, t in [(Timeframe.M1, Timeframe.M15), (Timeframe.M5, Timeframe.H1)]:
            assert resample([], s, t).candles == ()

    def test_unsorted_input_gives_the_same_result_as_sorted(self) -> None:
        src = series(MON, 30, Timeframe.M1)
        shuffled = src[::-1]
        assert resample(shuffled, Timeframe.M1, Timeframe.M5) == resample(
            src, Timeframe.M1, Timeframe.M5
        )

    def test_duplicate_open_times_are_dropped_first_wins_and_counted(self) -> None:
        src = series(MON, 5, Timeframe.M1)
        dup = Candle(src[2].open_time, 9.0, 9.5, 8.5, 9.1, 999.0)
        r = resample([*src, dup], Timeframe.M1, Timeframe.M5)
        assert r.duplicates_dropped == 1
        assert r.candles[0].volume == 50.0
        assert r.candles[0].high < 9.0

    def test_naive_open_time_is_refused(self) -> None:
        with pytest.raises(ValueError):
            resample([bar(datetime(2024, 1, 8))], Timeframe.M1, Timeframe.M5)

    def test_no_output_price_was_absent_from_the_input(self) -> None:
        """Resampling selects; it never averages or invents a price."""
        src = series(MON, 120, Timeframe.M1, skip={3, 40, 41, 77})
        pool = {p for c in src for p in (c.open, c.high, c.low, c.close)}
        for c in resample(src, Timeframe.M1, Timeframe.H1).candles:
            assert {c.open, c.high, c.low, c.close} <= pool

    def test_total_volume_is_conserved(self) -> None:
        src = series(MON, 120, Timeframe.M1, skip={3, 40})
        out = resample(src, Timeframe.M1, Timeframe.M15).candles
        assert sum(c.volume for c in out) == sum(c.volume for c in src)

    def test_resampled_output_validates_clean(self) -> None:
        src = open_market_series(MON, MON + timedelta(days=2), Timeframe.M1)
        out = resample(src, Timeframe.M1, Timeframe.H1)
        assert out.incomplete_buckets == 0
        assert validate(out.candles, "EURUSD", Timeframe.H1).grade == "good"


class TestSliceWindow:
    def setup_method(self) -> None:
        self.candles = series(MON, 10, Timeframe.H1)

    def test_start_inclusive_end_exclusive(self) -> None:
        w = slice_window(self.candles, MON + timedelta(hours=2), MON + timedelta(hours=5))
        assert [c.open_time.hour for c in w] == [2, 3, 4]

    def test_open_ended_bounds(self) -> None:
        assert len(slice_window(self.candles, None, None)) == 10
        assert len(slice_window(self.candles, MON + timedelta(hours=7), None)) == 3
        assert len(slice_window(self.candles, None, MON + timedelta(hours=2))) == 2

    def test_empty_and_inverted_windows(self) -> None:
        assert slice_window(self.candles, MON + timedelta(days=5), None) == ()
        assert (
            slice_window(self.candles, MON + timedelta(hours=5), MON + timedelta(hours=2))
            == ()
        )

    def test_naive_bound_is_refused(self) -> None:
        with pytest.raises(ValueError):
            slice_window(self.candles, datetime(2024, 1, 8), None)
