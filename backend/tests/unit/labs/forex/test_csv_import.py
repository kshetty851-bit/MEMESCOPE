"""CSV import: format detection, UTC conversion, and refusing bad rows.

The shared property: a row is either imported exactly as quoted (rounded only
to the instrument's precision) or rejected with its line number. Nothing is
repaired, and no rejected row leaves a trace in the candles.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.labs.forex.csv_import import MAX_STORED_ERRORS, parse_csv
from app.labs.forex.types import Candle, Timeframe

pytestmark = pytest.mark.unit

HEADER = "timestamp,open,high,low,close,volume\n"


class TestGeneric:
    def test_iso_utc_row_is_imported_verbatim(self) -> None:
        r = parse_csv(
            HEADER + "2024-01-02T10:05:00Z,1.10429,1.10440,1.10420,1.10435,12\n",
            symbol="EURUSD",
            timeframe=Timeframe.M5,
        )
        assert r.detected_format == "generic"
        assert r.candles == (
            Candle(
                datetime(2024, 1, 2, 10, 5, tzinfo=UTC), 1.10429, 1.1044, 1.1042, 1.10435, 12.0
            ),
        )
        assert (r.rows_total, r.rows_accepted, r.error_count, r.notes) == (1, 1, 0, ())

    def test_naive_timestamps_take_the_given_offset_and_say_otherwise_utc(self) -> None:
        text = HEADER + "2024-01-02 10:05:00,1.1,1.2,1.0,1.1,0\n"
        shifted = parse_csv(
            text, symbol="EURUSD", timeframe=Timeframe.M5, utc_offset_minutes=120
        )
        assert shifted.candles[0].open_time == datetime(2024, 1, 2, 8, 5, tzinfo=UTC)
        assert shifted.notes == ()
        plain = parse_csv(text, symbol="EURUSD", timeframe=Timeframe.M5)
        assert plain.candles[0].open_time == datetime(2024, 1, 2, 10, 5, tzinfo=UTC)
        assert plain.notes == ("naive_timestamps_assumed_utc",)

    def test_explicit_offset_in_the_timestamp_beats_the_parameter(self) -> None:
        """An offset written in the data is a fact; the caller's guess must not override it."""
        r = parse_csv(
            HEADER + "2024-01-02T10:05:00+02:00,1.1,1.2,1.0,1.1,0\n",
            symbol="EURUSD",
            timeframe=Timeframe.M5,
            utc_offset_minutes=-300,
        )
        assert r.candles[0].open_time == datetime(2024, 1, 2, 8, 5, tzinfo=UTC)

    def test_unix_seconds_and_milliseconds(self) -> None:
        t = int(datetime(2024, 1, 2, 10, 5, tzinfo=UTC).timestamp())
        r = parse_csv(
            "time,open,high,low,close\n"
            f"{t},1.1,1.2,1.0,1.1\n"
            f"{t * 1000 + 300_000},1.1,1.2,1.0,1.1\n",
            symbol="EURUSD",
            timeframe=Timeframe.M5,
        )
        assert [c.open_time.minute for c in r.candles] == [5, 10]
        assert r.candles[0].volume == 0.0
        assert r.notes == ()  # absolute times need no assumption

    def test_implausible_small_integer_is_not_read_as_a_1970_timestamp(self) -> None:
        r = parse_csv(
            "date,open,high,low,close\n20240102,1.1,1.2,1.0,1.1\n",
            symbol="EURUSD",
            timeframe=Timeframe.M5,
        )
        assert r.candles == () and r.error_count == 1

    def test_separate_date_and_time_columns_and_semicolons(self) -> None:
        r = parse_csv(
            "Date;Time;Open;High;Low;Close;Volume\n2024.01.02;10:05;1.1;1.2;1.0;1.1;7\n",
            symbol="EURUSD",
            timeframe=Timeframe.M5,
        )
        assert r.candles[0].open_time == datetime(2024, 1, 2, 10, 5, tzinfo=UTC)
        assert r.candles[0].volume == 7.0

    def test_bom_and_uppercase_headers(self) -> None:
        r = parse_csv(
            "﻿TIMESTAMP,OPEN,HIGH,LOW,CLOSE\n2024-01-02T10:05:00Z,1.1,1.2,1.0,1.1\n",
            symbol="EURUSD",
            timeframe=Timeframe.M5,
        )
        assert r.rows_accepted == 1

    def test_header_without_required_columns_is_reported_and_nothing_imported(self) -> None:
        r = parse_csv("foo,bar\n1,2\n", symbol="EURUSD", timeframe=Timeframe.M5)
        assert r.candles == () and r.error_count == 1
        assert r.errors[0].line == 1 and "open" in r.errors[0].message

    def test_prices_are_rounded_to_instrument_precision_only(self) -> None:
        eur = parse_csv(
            HEADER + "2024-01-02T10:05:00Z,1.1042949,1.1044,1.1042,1.10435,0\n",
            symbol="EURUSD",
            timeframe=Timeframe.M5,
        )
        assert eur.candles[0].open == 1.10429
        jpy = parse_csv(
            HEADER + "2024-01-02T10:05:00Z,150.1234,150.2,150.1,150.15,0\n",
            symbol="USDJPY",
            timeframe=Timeframe.M5,
        )
        assert jpy.candles[0].open == 150.123

    def test_empty_text_yields_empty_result(self) -> None:
        r = parse_csv("", symbol="EURUSD", timeframe=Timeframe.M5)
        assert (r.candles, r.errors, r.rows_total) == ((), (), 0)


class TestHistData:
    LINE = "20240102 170000;1.104290;1.104300;1.104250;1.104280;0\n"

    def test_est_is_converted_with_a_note_when_no_offset_given(self) -> None:
        """HistData is fixed EST (UTC-5, no DST); 17:00 EST is 22:00 UTC."""
        r = parse_csv(self.LINE, symbol="EURUSD", timeframe=Timeframe.M1, fmt="histdata")
        assert r.candles[0].open_time == datetime(2024, 1, 2, 22, 0, tzinfo=UTC)
        assert r.notes == ("histdata_est_fixed_utc_minus_5",)
        assert r.detected_format == "histdata"

    def test_est_applies_in_summer_too(self) -> None:
        """No DST: a July timestamp is still UTC-5, not UTC-4."""
        r = parse_csv(
            "20240702 170000;1.1;1.2;1.0;1.1;0\n",
            symbol="EURUSD",
            timeframe=Timeframe.M1,
            fmt="histdata",
        )
        assert r.candles[0].open_time == datetime(2024, 7, 2, 22, 0, tzinfo=UTC)

    def test_explicit_nonzero_offset_wins_and_adds_no_note(self) -> None:
        r = parse_csv(
            self.LINE,
            symbol="EURUSD",
            timeframe=Timeframe.M1,
            fmt="histdata",
            utc_offset_minutes=60,
        )
        assert r.candles[0].open_time == datetime(2024, 1, 2, 16, 0, tzinfo=UTC)
        assert r.notes == ()

    def test_auto_detects_histdata_and_applies_the_same_rule(self) -> None:
        r = parse_csv(self.LINE, symbol="EURUSD", timeframe=Timeframe.M1)
        assert r.detected_format == "histdata"
        assert r.notes == ("histdata_est_fixed_utc_minus_5",)

    def test_volume_field_is_optional(self) -> None:
        r = parse_csv(
            "20240102 170000;1.1;1.2;1.0;1.1\n",
            symbol="EURUSD",
            timeframe=Timeframe.M1,
            fmt="histdata",
        )
        assert r.candles[0].volume == 0.0


class TestMetaTrader:
    def test_headerless_comma_form_is_detected(self) -> None:
        r = parse_csv(
            "2024.01.02,17:00,1.10429,1.10430,1.10425,1.10428,12\n",
            symbol="EURUSD",
            timeframe=Timeframe.M1,
        )
        assert r.detected_format == "metatrader"
        assert r.candles[0].open_time == datetime(2024, 1, 2, 17, 0, tzinfo=UTC)
        assert r.candles[0].volume == 12.0
        assert r.notes == ("metatrader_server_time_assumed_utc",)

    def test_server_offset_is_applied_and_clears_the_note(self) -> None:
        r = parse_csv(
            "2024.01.02,17:00,1.1,1.2,1.0,1.1,1\n",
            symbol="EURUSD",
            timeframe=Timeframe.M1,
            fmt="metatrader",
            utc_offset_minutes=120,
        )
        assert r.candles[0].open_time == datetime(2024, 1, 2, 15, 0, tzinfo=UTC)
        assert r.notes == ()

    def test_mt5_tab_separated_with_header_prefers_tick_volume(self) -> None:
        text = (
            "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
            "2024.01.02\t17:00:00\t1.10429\t1.10430\t1.10425\t1.10428\t44\t0\t3\n"
        )
        r = parse_csv(text, symbol="EURUSD", timeframe=Timeframe.M1)
        assert r.detected_format == "metatrader"
        assert r.candles[0].volume == 44.0
        assert r.candles[0].close == 1.10428
        assert r.rows_total == 1


class TestRejection:
    def test_each_bad_row_is_skipped_with_its_own_line_number(self) -> None:
        text = (
            HEADER
            + "2024-01-02T10:00:00Z,1.1,1.2,1.0,1.1,0\n"  # line 2 ok
            + "\n"  # line 3 blank, ignored
            + "2024-01-02T10:05:00Z,abc,1.2,1.0,1.1,0\n"  # line 4 bad price
            + "2024-01-02T10:10:00Z,1.1,1.0,1.0,1.1,0\n"  # line 5 high < close
            + "2024-01-02T10:15:00Z,1.1,1.2,1.15,1.1,0\n"  # line 6 low > open
            + "2024-01-02T10:20:00Z,0,1.2,0,1.1,0\n"  # line 7 non-positive
            + "2024-01-02T10:21:00Z,1.1,1.2,1.0,1.1,0\n"  # line 8 not on 5m grid
            + "garbage,1.1,1.2,1.0,1.1,0\n"  # line 9 bad timestamp
            + "2024-01-02T10:30:00Z,1.1,1.2\n"  # line 10 short row
            + "2024-01-02T10:35:00Z,1.1,1.2,1.0,1.1,-5\n"  # line 11 bad volume
            + "2024-01-02T10:40:00Z,1.1,nan,1.0,1.1,0\n"  # line 12 not finite
        )
        r = parse_csv(text, symbol="EURUSD", timeframe=Timeframe.M5)
        assert [c.open_time.minute for c in r.candles] == [0]
        assert [e.line for e in r.errors] == [4, 5, 6, 7, 8, 9, 10, 11, 12]
        assert (r.rows_total, r.rows_accepted, r.error_count) == (10, 1, 9)
        assert "aligned to 5m" in r.errors[4].message

    def test_duplicate_timestamp_keeps_the_first_and_reports_the_rest(self) -> None:
        r = parse_csv(
            HEADER
            + "2024-01-02T10:00:00Z,1.1,1.2,1.0,1.1,1\n"
            + "2024-01-02T10:00:00Z,2.0,2.2,1.9,2.1,2\n",
            symbol="EURUSD",
            timeframe=Timeframe.M5,
        )
        assert [c.open for c in r.candles] == [1.1]
        assert r.errors[0].line == 3 and r.errors[0].message == "duplicate timestamp"

    def test_invalid_first_row_does_not_reserve_the_timestamp(self) -> None:
        """A rejected row must not shadow a later good row with the same timestamp."""
        r = parse_csv(
            HEADER
            + "2024-01-02T10:00:00Z,1.1,1.0,1.0,1.1,1\n"
            + "2024-01-02T10:00:00Z,1.1,1.2,1.0,1.1,1\n",
            symbol="EURUSD",
            timeframe=Timeframe.M5,
        )
        assert r.rows_accepted == 1 and r.errors[0].line == 2

    def test_equal_open_high_low_close_is_valid(self) -> None:
        r = parse_csv(
            HEADER + "2024-01-02T10:00:00Z,1.1,1.1,1.1,1.1,0\n",
            symbol="EURUSD",
            timeframe=Timeframe.M5,
        )
        assert r.rows_accepted == 1

    def test_error_storage_is_capped_but_every_error_is_counted(self) -> None:
        rows = "".join(f"bad{i},1,1,1,1,0\n" for i in range(MAX_STORED_ERRORS + 50))
        r = parse_csv(HEADER + rows, symbol="EURUSD", timeframe=Timeframe.M5)
        assert len(r.errors) == MAX_STORED_ERRORS
        assert r.error_count == MAX_STORED_ERRORS + 50
        assert r.rows_total == MAX_STORED_ERRORS + 50

    def test_output_is_sorted_even_if_the_file_is_not(self) -> None:
        r = parse_csv(
            HEADER
            + "2024-01-02T10:10:00Z,1.1,1.2,1.0,1.1,0\n"
            + "2024-01-02T10:00:00Z,1.1,1.2,1.0,1.1,0\n"
            + "2024-01-02T10:05:00Z,1.1,1.2,1.0,1.1,0\n",
            symbol="EURUSD",
            timeframe=Timeframe.M5,
        )
        times = [c.open_time for c in r.candles]
        assert times == sorted(times)

    def test_accepted_prices_are_exactly_the_quoted_ones(self) -> None:
        """Nothing is smoothed or adjusted on the way in."""
        quoted = [(1.10429, 1.1044, 1.1042, 1.10435), (1.10435, 1.10436, 1.1043, 1.10431)]
        body = "".join(
            f"2024-01-02T10:{5 * i:02d}:00Z,{o},{h},{lo},{c},0\n"
            for i, (o, h, lo, c) in enumerate(quoted)
        )
        r = parse_csv(HEADER + body, symbol="EURUSD", timeframe=Timeframe.M5)
        assert [(c.open, c.high, c.low, c.close) for c in r.candles] == quoted


class TestArguments:
    def test_unknown_symbol_is_a_value_error(self) -> None:
        with pytest.raises(ValueError):
            parse_csv(HEADER, symbol="XAUUSD", timeframe=Timeframe.M5)

    def test_unknown_format_is_a_value_error(self) -> None:
        with pytest.raises(ValueError):
            parse_csv(HEADER, symbol="EURUSD", timeframe=Timeframe.M5, fmt="excel")

    def test_absurd_offset_is_a_value_error(self) -> None:
        with pytest.raises(ValueError):
            parse_csv(HEADER, symbol="EURUSD", timeframe=Timeframe.M5, utc_offset_minutes=5000)
