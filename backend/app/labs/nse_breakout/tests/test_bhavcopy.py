"""The parser, against a saved slice of a REAL exchange file.

A synthetic CSV would only prove the parser reads a CSV I wrote. The fixture
is 400 rows taken verbatim from `BhavCopy_NSE_CM_0_0_0_20260910_F_0000.csv.zip`,
so it carries the real column order, the real series mix, and the real
oddities — gold bonds, government securities, SME names.
"""

from __future__ import annotations

import io
import pathlib
import zipfile
from datetime import date
from decimal import Decimal

import pytest

from app.labs.nse_breakout import bhavcopy, config

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "bhavcopy_20260910.csv"
REAL = FIXTURE.read_text()


def test_the_real_file_parses_into_equity_bars() -> None:
    bars = list(bhavcopy.parse(REAL))
    assert bars, "the fixture should contain tradeable equities"
    assert all(b.series in config.ALLOWED_SERIES for b in bars)
    assert all(b.date == date(2026, 9, 10) for b in bars)
    assert all(b.open > 0 and b.close > 0 for b in bars)


def test_every_parsed_bar_is_internally_consistent() -> None:
    """High above both ends, low below both. The exchange has published rows
    where this is false; one bad bar poisons every level computed from it."""
    for b in bhavcopy.parse(REAL):
        assert b.low <= b.open <= b.high, b.symbol
        assert b.low <= b.close <= b.high, b.symbol


def test_non_equity_instruments_are_dropped() -> None:
    """The file carries gold bonds, government securities and SME names. None
    is a breakout candidate and all of them are in the same CSV."""
    symbols = {b.symbol for b in bhavcopy.parse(REAL)}
    raw_series = {line.split(",")[8] for line in REAL.splitlines()[1:] if line}
    assert raw_series - config.ALLOWED_SERIES, "fixture should contain other series"
    for line in REAL.splitlines()[1:]:
        fields = line.split(",")
        if len(fields) > 8 and fields[8] not in config.ALLOWED_SERIES:
            assert fields[7] not in symbols or fields[7] in {
                b.symbol for b in bhavcopy.parse(REAL) if b.series in config.ALLOWED_SERIES}


def test_a_row_with_a_broken_price_is_dropped_not_defaulted() -> None:
    """A zero low would sit under every future support level for ever."""
    header = REAL.splitlines()[0]
    good = next(line for line in REAL.splitlines()[1:] if ",EQ," in line)
    fields = good.split(",")
    hdr = header.split(",")
    fields[hdr.index("LwPric")] = "0"
    assert list(bhavcopy.parse("\n".join([header, "\n".join([good])]))), "control"
    assert not list(bhavcopy.parse("\n".join([header, ",".join(fields)])))


def test_a_high_below_the_low_is_refused() -> None:
    header = REAL.splitlines()[0]
    hdr = header.split(",")
    good = next(line for line in REAL.splitlines()[1:] if ",EQ," in line)
    fields = good.split(",")
    fields[hdr.index("HghPric")] = "1"
    fields[hdr.index("LwPric")] = "999999"
    assert not list(bhavcopy.parse("\n".join([header, ",".join(fields)])))


def test_missing_columns_raise_rather_than_return_nothing() -> None:
    """A format change and an empty file must not look the same."""
    with pytest.raises(bhavcopy.BhavcopyError, match="missing columns"):
        list(bhavcopy.parse("A,B,C\n1,2,3\n"))


def test_a_404_page_is_not_mistaken_for_a_zip() -> None:
    with pytest.raises(bhavcopy.BhavcopyError, match="not a ZIP"):
        bhavcopy.unzip(b"<html><title>404</title></html>")
    with pytest.raises(bhavcopy.BhavcopyError, match="corrupt ZIP"):
        bhavcopy.unzip(b"PK\x03\x04garbage")


def test_a_zip_round_trips() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.csv", REAL)
    assert bhavcopy.unzip(buf.getvalue()).splitlines()[0] == REAL.splitlines()[0]


def test_a_zip_without_a_csv_is_refused() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("readme.txt", "nothing here")
    with pytest.raises(bhavcopy.BhavcopyError, match="no CSV"):
        bhavcopy.unzip(buf.getvalue())


# --- the index file -------------------------------------------------------------

INDEX_CSV = (
    "Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,"
    "Closing Index Value,Points Change,Change(%),Volume,Turnover (Rs. Cr.)\n"
    "Nifty 50,10-09-2026,23300.00,23400.10,23250.00,23356.25,56.25,0.24,1,2\n"
    "Nifty Bank,10-09-2026,50000.00,50200.00,49900.00,50100.00,100.0,0.20,1,2\n")


def test_the_nifty_close_is_picked_out_of_the_index_file() -> None:
    parsed = bhavcopy.parse_index_closes(INDEX_CSV)
    assert parsed == (date(2026, 9, 10), Decimal("23356.25"))


def test_an_absent_index_is_none_not_an_exception() -> None:
    """Pre-decided: a missing Nifty close makes one window's relative return
    null. It must never take an ingest down."""
    assert bhavcopy.parse_index_closes(INDEX_CSV, "Nifty Nonexistent") is None
    assert bhavcopy.parse_index_closes("") is None
