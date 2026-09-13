"""Dukascopy's `.bi5` tick format, and the aggregation to 1-minute candles.

Pure functions over bytes. No network, no DB — so the decoder is testable
against a file on disk and the aggregator against a hand-written tick list.

## The format

An hour-file is LZMA-compressed (non-streamed, `.lzma`/alone container) and
decompresses to a flat array of 20-byte big-endian records:

    >3I2f  =  (milliseconds since the hour, ask_points, bid_points,
               ask_volume, bid_volume)

`*_points` are the quote divided by the instrument's point size — 1e-5 for
EUR/USD, so 105604 is 1.05604. An hour the feed has no data for is served as
zero bytes, which decodes to zero records rather than raising.

## The other format, which this lab reads but does not load from

Dukascopy also publishes its OWN 1-minute candles, one file per side per day:
`EURUSD/<yyyy>/<mm>/<dd>/BID_candles_min_1.bi5`. Same LZMA container, 24-byte
records of `>5If` = (seconds into the day, open, close, low, high, volume) —
note that the order is O, C, L, H, and that a full day is exactly 1,440
records whether the market traded or not.

They are not what the dataset is built from: the brief asks for ticks
aggregated here, and an aggregation this lab did not do is one it cannot check.
They are used for exactly that checking — `verify_against_published` compares
them against the stored candles, which is an independent party's arithmetic
over the same ticks.
"""

from __future__ import annotations

import lzma
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.labs.forex_lab import config

_RECORD = struct.Struct(">3I2f")
_RECORD_SIZE = _RECORD.size  # 20


@dataclass(frozen=True, slots=True)
class Tick:
    ts: datetime
    bid: float
    ask: float


@dataclass(frozen=True, slots=True)
class Candle:
    """One minute. `minute` is the minute's opening instant, UTC."""

    minute: datetime
    bid_open: float
    bid_high: float
    bid_low: float
    bid_close: float
    ask_open: float
    ask_high: float
    ask_low: float
    ask_close: float
    ticks: int

    @property
    def mid_open(self) -> float:
        return (self.bid_open + self.ask_open) / 2.0

    @property
    def mid_high(self) -> float:
        return (self.bid_high + self.ask_high) / 2.0

    @property
    def mid_low(self) -> float:
        return (self.bid_low + self.ask_low) / 2.0

    @property
    def mid_close(self) -> float:
        return (self.bid_close + self.ask_close) / 2.0


class TickDecodeError(ValueError):
    """The bytes are not a Dukascopy hour-file.

    Raised rather than returning an empty list, because the CDN answers a
    transient failure with an HTML error page, and an HTML page silently
    decoded as "this hour had no ticks" would write a hole into the dataset
    that the integrity check would then have to find.
    """


def decode_hour(
    raw: bytes, hour_start: datetime, scale: float = config.POINT_SCALE
) -> list[Tick]:
    """Decompress and unpack one hour-file. Empty input is an empty hour."""
    if not raw:
        return []
    try:
        data = lzma.decompress(raw)
    except lzma.LZMAError as exc:  # an HTML error page, or a truncated body
        raise TickDecodeError(f"not LZMA: {exc}") from exc
    if len(data) % _RECORD_SIZE:
        raise TickDecodeError(
            f"{len(data)} bytes is not a whole number of {_RECORD_SIZE}-byte records"
        )
    out: list[Tick] = []
    for offset in range(0, len(data), _RECORD_SIZE):
        ms, ask_pts, bid_pts, _av, _bv = _RECORD.unpack_from(data, offset)
        out.append(
            Tick(
                ts=hour_start + timedelta(milliseconds=ms),
                bid=bid_pts * scale,
                ask=ask_pts * scale,
            )
        )
    return out


def to_minute_candles(ticks: list[Tick]) -> list[Candle]:
    """Aggregate ticks into 1-minute bid/ask OHLC.

    A minute with no tick gets no candle — the absence is the signal the gap
    check reads. Ticks are assumed already in file order (Dukascopy writes them
    ascending); out-of-order input would only disturb open/close, so the
    ordering is asserted rather than sorted for, to catch a format change
    instead of papering over one.
    """
    if not ticks:
        return []
    out: list[Candle] = []
    cur_minute: datetime | None = None
    bo = bh = bl = bc = ao = ah = al = ac = 0.0
    n = 0
    prev_ts = ticks[0].ts
    for t in ticks:
        if t.ts < prev_ts:
            raise TickDecodeError(f"ticks out of order at {t.ts}")
        prev_ts = t.ts
        m = t.ts.replace(second=0, microsecond=0)
        if m != cur_minute:
            if cur_minute is not None:
                out.append(Candle(cur_minute, bo, bh, bl, bc, ao, ah, al, ac, n))
            cur_minute = m
            bo = bh = bl = bc = t.bid
            ao = ah = al = ac = t.ask
            n = 0
        else:
            bh = t.bid if t.bid > bh else bh
            bl = t.bid if t.bid < bl else bl
            bc = t.bid
            ah = t.ask if t.ask > ah else ah
            al = t.ask if t.ask < al else al
            ac = t.ask
        n += 1
    assert cur_minute is not None
    out.append(Candle(cur_minute, bo, bh, bl, bc, ao, ah, al, ac, n))
    return out


_CANDLE = struct.Struct(">5If")


def decode_day_candles(
    raw: bytes, day: datetime, scale: float = config.POINT_SCALE
) -> dict[datetime, tuple]:
    """Dukascopy's own 1-minute candles for one day and one side.

    Returns {minute: (open, high, low, close)} — reordered from the file's
    O, C, L, H. Minutes the market did not trade are present in the file as
    flat rows with zero volume; they are dropped, because this lab's own table
    has no row for a minute with no tick and comparing a row against a
    placeholder would report a difference that is not one.
    """
    if not raw:
        return {}
    try:
        data = lzma.decompress(raw)
    except lzma.LZMAError as exc:
        raise TickDecodeError(f"not LZMA: {exc}") from exc
    if len(data) % _CANDLE.size:
        raise TickDecodeError(
            f"{len(data)} bytes is not a whole number of {_CANDLE.size}-byte candles"
        )
    out: dict[datetime, tuple] = {}
    for offset in range(0, len(data), _CANDLE.size):
        sec, o, c, lo, hi, vol = _CANDLE.unpack_from(data, offset)
        if vol <= 0:
            continue
        out[day + timedelta(seconds=sec)] = (
            o * scale,
            hi * scale,
            lo * scale,
            c * scale,
        )
    return out


def day_candles_url(symbol: str, day: datetime, side: str) -> str:
    """`side` is BID or ASK. Zero-based month, as everywhere in this feed."""
    return (
        f"{config.DUKASCOPY_BASE}/{symbol}/{day.year:04d}/{day.month - 1:02d}/"
        f"{day.day:02d}/{side.upper()}_candles_min_1.bi5"
    )


def hour_url(symbol: str, hour_start: datetime) -> str:
    """Dukascopy paths use a ZERO-BASED month. January is `00`."""
    return (
        f"{config.DUKASCOPY_BASE}/{symbol}/{hour_start.year:04d}/"
        f"{hour_start.month - 1:02d}/{hour_start.day:02d}/{hour_start.hour:02d}h_ticks.bi5"
    )
