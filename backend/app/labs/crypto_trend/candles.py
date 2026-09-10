"""Kline rows -> candles, and gap detection. Pure; no I/O."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from itertools import pairwise

INTERVAL_MS: dict[str, int] = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


@dataclass(frozen=True, slots=True)
class Candle:
    symbol: str
    timeframe: str
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    close_time: datetime


def from_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def to_ms(dt: datetime) -> int:
    # round, not int: 1789045199.999 * 1000 is not exactly representable.
    return round(dt.timestamp() * 1000)


def parse_klines(
    symbol: str, timeframe: str, rows: Iterable[Sequence], *, now_ms: int,
) -> list[Candle]:
    """Binance kline rows, keeping only candles that have CLOSED.

    Binance returns the candle currently forming as the last row; storing it
    would write a close that is still moving. `close_time < now` is the test.
    """
    return [
        Candle(symbol, timeframe, from_ms(int(r[0])),
               Decimal(str(r[1])), Decimal(str(r[2])), Decimal(str(r[3])), Decimal(str(r[4])),
               Decimal(str(r[5])), from_ms(int(r[6])))
        for r in rows
        if int(r[6]) < now_ms
    ]


def find_gaps(open_times_ms: Iterable[int], interval_ms: int) -> list[tuple[int, int]]:
    """Ranges of missing candles between stored ones, as
    `(first_missing_open_ms, last_missing_open_ms)`. Order of input is free."""
    times = sorted(set(open_times_ms))
    return [
        (prev + interval_ms, nxt - interval_ms)
        for prev, nxt in pairwise(times)
        if nxt - prev > interval_ms
    ]
