"""The Dukascopy decoder and the minute aggregation.

The decoder is checked against a REAL hour-file, downloaded once and committed
next to this test, because a decoder verified only against bytes this repo
wrote proves that the repo agrees with itself.
"""

from __future__ import annotations

import lzma
import struct
from datetime import UTC, datetime, timedelta

import pytest

from app.labs.forex_lab.ticks import (
    Candle, Tick, TickDecodeError, decode_hour, hour_url, to_minute_candles,
)

HOUR = datetime(2023, 1, 3, 14, 0, tzinfo=UTC)


def pack(records) -> bytes:
    """Build a .bi5 body the way Dukascopy does: big-endian, 20 bytes a tick."""
    raw = b"".join(struct.pack(">3I2f", ms, ask, bid, av, bv)
                   for ms, ask, bid, av, bv in records)
    return lzma.compress(raw, format=lzma.FORMAT_ALONE)


# --- the format ---------------------------------------------------------------


def test_decodes_points_at_the_instrument_s_scale():
    raw = pack([(276, 105604, 105599, 2.17, 0.44), (378, 105605, 105600, 0.9, 3.6)])
    ticks = decode_hour(raw, HOUR)
    assert len(ticks) == 2
    assert ticks[0].ask == pytest.approx(1.05604)
    assert ticks[0].bid == pytest.approx(1.05599)
    assert ticks[0].ts == HOUR + timedelta(milliseconds=276)
    assert ticks[1].ts == HOUR + timedelta(milliseconds=378)


def test_an_empty_body_is_an_empty_hour_not_an_error():
    assert decode_hour(b"", HOUR) == []


def test_an_html_error_page_raises_rather_than_reading_as_an_empty_hour():
    """The CDN answers a transient failure with a styled HTML page. Decoded as
    "no ticks this hour" it would write a hole into the dataset that the
    integrity check would then have to go and find."""
    with pytest.raises(TickDecodeError):
        decode_hour(b"<!DOCTYPE html><html><body>503</body></html>", HOUR)


def test_a_truncated_body_raises():
    raw = pack([(0, 105604, 105599, 1.0, 1.0)])
    body = lzma.decompress(raw)[:-3]
    with pytest.raises(TickDecodeError):
        decode_hour(lzma.compress(body, format=lzma.FORMAT_ALONE), HOUR)


def test_the_url_uses_a_zero_based_month():
    """January is 00. Getting this wrong loads a month of the wrong prices and
    nothing anywhere raises."""
    assert hour_url("EURUSD", datetime(2023, 1, 3, 14, tzinfo=UTC)).endswith(
        "EURUSD/2023/00/03/14h_ticks.bi5")
    assert hour_url("EURUSD", datetime(2020, 12, 31, 0, tzinfo=UTC)).endswith(
        "EURUSD/2020/11/31/00h_ticks.bi5")


# --- aggregation --------------------------------------------------------------


def _t(sec: float, bid: float, ask: float) -> Tick:
    return Tick(HOUR + timedelta(seconds=sec), bid, ask)


def test_one_minute_of_ticks_becomes_one_ohlc_candle():
    ticks = [_t(1, 1.0500, 1.0501), _t(20, 1.0510, 1.0512),
             _t(40, 1.0495, 1.0496), _t(59, 1.0505, 1.0506)]
    (c,) = to_minute_candles(ticks)
    assert c.minute == HOUR
    assert (c.bid_open, c.bid_high, c.bid_low, c.bid_close) == (1.0500, 1.0510, 1.0495, 1.0505)
    assert (c.ask_open, c.ask_high, c.ask_low, c.ask_close) == (1.0501, 1.0512, 1.0496, 1.0506)
    assert c.ticks == 4
    assert c.mid_open == pytest.approx((1.0500 + 1.0501) / 2)


def test_a_minute_with_no_tick_gets_no_candle():
    """The absence IS the signal — it is what the gap check reads."""
    ticks = [_t(10, 1.05, 1.0501), _t(130, 1.06, 1.0601)]  # 00:00:10 and 00:02:10
    candles = to_minute_candles(ticks)
    assert [c.minute.minute for c in candles] == [0, 2]


def test_out_of_order_ticks_raise_rather_than_being_sorted():
    """A silent sort would hide a format change behind plausible candles."""
    with pytest.raises(TickDecodeError):
        to_minute_candles([_t(30, 1.05, 1.0501), _t(10, 1.06, 1.0601)])


def test_no_ticks_is_no_candles():
    assert to_minute_candles([]) == []


def test_bid_never_exceeds_ask_in_an_aggregate_when_it_never_did_in_a_tick():
    """The integrity check asserts this over the whole dataset; the aggregator
    is the only place that could break it."""
    ticks = [_t(i, 1.0500 + i * 1e-5, 1.0501 + i * 1e-5) for i in range(60)]
    (c,) = to_minute_candles(ticks)
    assert c.bid_open <= c.ask_open and c.bid_high <= c.ask_high
    assert c.bid_low <= c.ask_low and c.bid_close <= c.ask_close


# --- the feed's own candles, used for cross-checking --------------------------


def pack_candles(records) -> bytes:
    """Dukascopy's candle format: 24 bytes, `>5If`, and the order is O, C, L, H
    — not the O, H, L, C everything else in the world uses."""
    raw = b"".join(struct.pack(">5If", sec, o, c, lo, hi, vol)
                   for sec, o, c, lo, hi, vol in records)
    return lzma.compress(raw, format=lzma.FORMAT_ALONE)


DAY = datetime(2023, 1, 3, 0, 0, tzinfo=UTC)


def test_day_candles_are_reordered_from_ocIh_to_ohlc():
    """Reading O, C, L, H as O, H, L, C would swap high and close on every
    candle and still look entirely plausible."""
    from app.labs.forex_lab.ticks import decode_day_candles

    got = decode_day_candles(pack_candles([(0, 106764, 106735, 106732, 106766, 471.4)]), DAY)
    assert got == {DAY: pytest.approx((1.06764, 1.06766, 1.06732, 1.06735))}


def test_a_minute_the_market_did_not_trade_is_dropped():
    """The feed writes 1,440 rows a day whether it traded or not. This lab's
    table has no row for a minute with no tick, so a zero-volume placeholder
    compared against nothing would report a difference that is not one."""
    from app.labs.forex_lab.ticks import decode_day_candles

    got = decode_day_candles(pack_candles([
        (0, 106764, 106735, 106732, 106766, 471.4),
        (60, 106735, 106735, 106735, 106735, 0.0),
    ]), DAY)
    assert list(got) == [DAY]


def test_the_day_candle_url_also_uses_a_zero_based_month():
    from app.labs.forex_lab.ticks import day_candles_url

    assert day_candles_url("EURUSD", DAY, "BID").endswith(
        "EURUSD/2023/00/03/BID_candles_min_1.bi5")
    assert day_candles_url("EURUSD", DAY, "ask").endswith(
        "EURUSD/2023/00/03/ASK_candles_min_1.bi5")


def test_a_truncated_candle_file_raises():
    from app.labs.forex_lab.ticks import decode_day_candles

    body = lzma.decompress(pack_candles([(0, 1, 1, 1, 1, 1.0)]))[:-5]
    with pytest.raises(TickDecodeError):
        decode_day_candles(lzma.compress(body, format=lzma.FORMAT_ALONE), DAY)
