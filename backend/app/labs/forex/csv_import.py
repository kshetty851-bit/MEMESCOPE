"""CSV candle import. Pure: takes text, returns candles and the rows it refused.

A bad row is rejected and reported with its line number; it is never repaired,
rounded into validity or replaced. Prices are rounded only to the instrument's
quote precision, which cannot change a digit the source quoted.

Formats
-------
generic    Header row; columns `timestamp|datetime|time|date` (a separate
           `date` + `time` pair is combined), `open`, `high`, `low`, `close`,
           optional `volume`. Delimiter `,` `;` or tab. Timestamps are ISO 8601
           (an offset or `Z` is honoured), or unix seconds / milliseconds as
           integers (> 1e11 means ms; below 1e9 is refused as implausible).
histdata   HistData.com ASCII M1, no header: `20240102 170000;o;h;l;c;v`. Those
           files are EST *without* DST (UTC-5 all year). With `fmt="histdata"`
           and `utc_offset_minutes == 0` the offset is therefore set to -300
           and the note `histdata_est_fixed_utc_minus_5` is returned. A file
           already converted to UTC cannot be expressed this way: import it
           as `generic`.
metatrader MT4/MT5 export: headerless `2024.01.02,17:00,o,h,l,c,v`, or the MT5
           header form `<DATE>\\t<TIME>\\t<OPEN>...` (tick volume preferred).
           Times are broker server time; with no offset given they are taken
           as UTC and `metatrader_server_time_assumed_utc` says so.

`utc_offset_minutes` is the source clock's offset east of UTC; UTC is the
local time minus it. Absolute timestamps (offset-bearing ISO, unix) ignore it.
"""

from __future__ import annotations

import csv
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.labs.forex.types import INSTRUMENTS, TIMEFRAME_SECONDS, Candle, Timeframe

MAX_STORED_ERRORS = 200
FORMATS = ("auto", "generic", "histdata", "metatrader")

NOTE_HISTDATA_EST = "histdata_est_fixed_utc_minus_5"
NOTE_MT_SERVER_AS_UTC = "metatrader_server_time_assumed_utc"
NOTE_NAIVE_AS_UTC = "naive_timestamps_assumed_utc"

_HISTDATA_OFFSET_MINUTES = -300
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MS_THRESHOLD = 10**11
# 8-digit "20240102" style dates are all-digit too; a floor keeps them from
# silently becoming a 1970 timestamp that happens to be minute-aligned.
_MIN_UNIX_SECONDS = 10**9
_HISTDATA_RE = re.compile(r"^\d{8} \d{6};")
_MT_ROW_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2},\d{1,2}:\d{2}")
_DOTTED_DATE_RE = re.compile(r"^(\d{4})[./](\d{2})[./](\d{2})")


@dataclass(frozen=True)
class RowError:
    line: int
    message: str


@dataclass(frozen=True)
class ParseResult:
    candles: tuple[Candle, ...]
    #: At most MAX_STORED_ERRORS; `error_count` is the true total.
    errors: tuple[RowError, ...]
    detected_format: str
    rows_total: int
    rows_accepted: int
    error_count: int = 0
    notes: tuple[str, ...] = ()


class _RejectError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class _Raw:
    when: datetime  # naive = source-local clock
    open: str
    high: str
    low: str
    close: str
    volume: str | None


_RowParser = Callable[[list[str]], _Raw]


def _parse_when(text: str) -> datetime:
    s = text.strip()
    if s.isascii() and s.isdigit():
        n = int(s)
        if n > _MS_THRESHOLD:
            delta = timedelta(milliseconds=n)
        elif n >= _MIN_UNIX_SECONDS:
            delta = timedelta(seconds=n)
        else:
            raise _RejectError("unparsable timestamp")
        try:
            return _EPOCH + delta
        except OverflowError:
            raise _RejectError("unparsable timestamp") from None
    try:
        return datetime.fromisoformat(_DOTTED_DATE_RE.sub(r"\1-\2-\3", s))
    except ValueError:
        raise _RejectError("unparsable timestamp") from None


def _norm_name(raw: str) -> str:
    return raw.strip().strip("<>\"' ").lower()


def _generic_parser(header: list[str]) -> _RowParser:
    names = [_norm_name(h) for h in header]

    def find(*aliases: str) -> int | None:
        return next((i for i, n in enumerate(names) if n in aliases), None)

    cols = {k: find(k) for k in ("open", "high", "low", "close")}
    missing = [k for k, i in cols.items() if i is None]
    ts, d, tm = find("timestamp", "datetime"), find("date"), find("time")
    when_cols: tuple[int, int | None] | None
    if ts is not None:
        when_cols = (ts, None)
    elif d is not None:
        when_cols = (d, tm)
    elif tm is not None:
        when_cols = (tm, None)
    else:
        when_cols = None
        missing.append("timestamp")
    if missing or when_cols is None:
        raise _RejectError("header missing column(s): " + ", ".join(missing))
    vol = find("volume", "vol", "tickvol", "tick_volume")
    o, h, lo, c = (cols[k] for k in ("open", "high", "low", "close"))
    assert o is not None and h is not None and lo is not None and c is not None
    first, second = when_cols
    need = max(i for i in (o, h, lo, c, first, second, vol) if i is not None) + 1

    def parse(row: list[str]) -> _Raw:
        if len(row) < need:
            raise _RejectError(f"expected at least {need} columns, got {len(row)}")
        text = row[first] if second is None else f"{row[first].strip()} {row[second].strip()}"
        return _Raw(
            _parse_when(text), row[o], row[h], row[lo], row[c],
            row[vol] if vol is not None else None,
        )  # fmt: skip

    return parse


def _histdata_row(row: list[str]) -> _Raw:
    if len(row) < 5:
        raise _RejectError(f"expected at least 5 fields, got {len(row)}")
    try:
        when = datetime.strptime(row[0].strip(), "%Y%m%d %H%M%S")
    except ValueError:
        raise _RejectError("unparsable timestamp") from None
    return _Raw(when, row[1], row[2], row[3], row[4], row[5] if len(row) > 5 else None)


def _mt_headerless_row(row: list[str]) -> _Raw:
    if len(row) < 6:
        raise _RejectError(f"expected at least 6 fields, got {len(row)}")
    when = _parse_when(f"{row[0].strip()} {row[1].strip()}")
    return _Raw(when, row[2], row[3], row[4], row[5], row[6] if len(row) > 6 else None)


def _detect(first_line: str) -> str:
    s = first_line.strip()
    if s.startswith("<"):
        return "metatrader"
    if _HISTDATA_RE.match(s):
        return "histdata"
    if _MT_ROW_RE.match(s):
        return "metatrader"
    return "generic"


def _delimiter(line: str) -> str:
    return max((",", ";", "\t"), key=lambda d: (line.count(d), d == ","))


def _split(line: str, delimiter: str) -> list[str]:
    try:
        return next(csv.reader([line], delimiter=delimiter))
    except (csv.Error, StopIteration):
        raise _RejectError("malformed row") from None


def _price(text: str, name: str, decimals: int) -> float:
    try:
        v = float(text.strip())
    except ValueError:
        raise _RejectError(f"unparsable {name}") from None
    if not math.isfinite(v):
        raise _RejectError(f"unparsable {name}")
    return round(v, decimals)


def _volume(text: str | None) -> float:
    if text is None or not text.strip():
        return 0.0
    try:
        v = float(text.strip())
    except ValueError:
        raise _RejectError("unparsable volume") from None
    if not math.isfinite(v) or v < 0:
        raise _RejectError("unparsable volume")
    return v


def _build(raw: _Raw, offset_minutes: int, decimals: int, step: int, tf: Timeframe) -> Candle:
    when = raw.when
    if when.tzinfo is None:
        when = (when - timedelta(minutes=offset_minutes)).replace(tzinfo=UTC)
    else:
        when = when.astimezone(UTC)
    o = _price(raw.open, "open", decimals)
    h = _price(raw.high, "high", decimals)
    lo = _price(raw.low, "low", decimals)
    c = _price(raw.close, "close", decimals)
    vol = _volume(raw.volume)
    if min(o, h, lo, c) <= 0:
        raise _RejectError("non-positive price")
    if h < max(o, c):
        raise _RejectError("high below open/close")
    if lo > min(o, c):
        raise _RejectError("low above open/close")
    seconds = when.hour * 3600 + when.minute * 60 + when.second
    if when.second or when.microsecond or seconds % step:
        raise _RejectError(f"timestamp not aligned to {tf.value}")
    return Candle(when, o, h, lo, c, vol)


def parse_csv(
    text: str,
    *,
    symbol: str,
    timeframe: Timeframe,
    fmt: str = "auto",
    utc_offset_minutes: int = 0,
) -> ParseResult:
    if symbol not in INSTRUMENTS:
        raise ValueError(f"unknown symbol {symbol!r}")
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r}")
    if abs(utc_offset_minutes) > 24 * 60:
        raise ValueError("utc_offset_minutes out of range")

    decimals = INSTRUMENTS[symbol].price_decimals
    step = TIMEFRAME_SECONDS[timeframe]
    lines = text.lstrip("﻿").splitlines()
    numbered = [(i, ln) for i, ln in enumerate(lines, start=1) if ln.strip()]

    resolved = fmt
    if fmt == "auto":
        resolved = _detect(numbered[0][1]) if numbered else "generic"

    notes: list[str] = []
    offset = utc_offset_minutes
    if resolved == "histdata" and offset == 0:
        offset = _HISTDATA_OFFSET_MINUTES
        notes.append(NOTE_HISTDATA_EST)

    errors: list[RowError] = []
    error_count = 0

    def reject(line: int, message: str) -> None:
        nonlocal error_count
        error_count += 1
        if len(errors) < MAX_STORED_ERRORS:
            errors.append(RowError(line, message))

    def finish(candles: list[Candle], total: int, naive: bool) -> ParseResult:
        if resolved == "metatrader" and offset == 0 and total:
            notes.append(NOTE_MT_SERVER_AS_UTC)
        elif resolved == "generic" and offset == 0 and naive:
            notes.append(NOTE_NAIVE_AS_UTC)
        candles.sort(key=lambda c: c.open_time)
        return ParseResult(
            tuple(candles),
            tuple(errors),
            resolved,
            total,
            len(candles),
            error_count,
            tuple(notes),
        )

    body = numbered
    delimiter = ";" if resolved == "histdata" else ","
    parser: _RowParser
    if resolved == "histdata":
        parser = _histdata_row
    elif numbered and (resolved == "generic" or numbered[0][1].lstrip().startswith("<")):
        head_no, head = numbered[0]
        delimiter = _delimiter(head)
        try:
            parser = _generic_parser(_split(head, delimiter))
        except _RejectError as e:
            reject(head_no, e.message)
            return finish([], 0, False)
        body = numbered[1:]
    else:
        parser = _mt_headerless_row

    accepted: list[Candle] = []
    seen: set[datetime] = set()
    naive_seen = False
    for line_no, line in body:
        try:
            raw = parser(_split(line, delimiter))
            naive_seen = naive_seen or raw.when.tzinfo is None
            candle = _build(raw, offset, decimals, step, timeframe)
            if candle.open_time in seen:
                raise _RejectError("duplicate timestamp")
        except _RejectError as e:
            reject(line_no, e.message)
            continue
        seen.add(candle.open_time)
        accepted.append(candle)
    return finish(accepted, len(body), naive_seen)
