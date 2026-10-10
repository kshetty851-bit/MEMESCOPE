"""Historical candle providers — the lab's only network seam.

Providers return what the source published and say so when it published
nothing. They never fill, interpolate or substitute a bar: a failed day raises
`ProviderError` so the caller records it and retries, and a day the source has
no file for is returned as `empty` so the gap shows up in the quality report.
"""

from __future__ import annotations

import lzma
import struct
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

import httpx

from app.labs.forex.sessions import is_weekend_closed
from app.labs.forex.types import INSTRUMENTS, Candle

DUKASCOPY_BASE_URL = "https://datafeed.dukascopy.com/datafeed"
_RECORD = struct.Struct(">5if")  # seconds, open, close, low, high (ints), volume (float32)
_SECONDS_PER_DAY = 86_400
_SATURDAY = 5

PROVIDERS_INFO: dict[str, dict[str, str]] = {
    "dukascopy": {
        "label": "Dukascopy historical feed",
        "cost": "free",
        "api_key": "none",
        "granularity": "1-minute candles, one file per UTC day",
        "history": "from about 2003 for the major pairs",
        "price_side": "BID",
        "url": DUKASCOPY_BASE_URL,
        "notes": "Unofficial public datafeed; no SLA. Tick volume only.",
    },
    "csv": {
        "label": "CSV upload",
        "cost": "free",
        "api_key": "none",
        "granularity": "whatever the file contains (1m, 5m, 15m, 1h)",
        "history": "whatever the file contains",
        "price_side": "as exported by the source",
        "url": "",
        "notes": "Manual upload: generic, HistData.com or MetaTrader exports.",
    },
}


class ProviderError(Exception):
    """A fetch failed in a way worth retrying later. Never a missing-data answer."""


@dataclass(frozen=True)
class DayFetch:
    day: date
    candles: tuple[Candle, ...]
    empty: bool
    source: str
    #: Zero-volume bars the feed emitted inside the weekend-closed window.
    dropped_flat: int = 0


class CandleProvider(Protocol):
    name: str

    async def fetch_day(self, symbol: str, day: date) -> DayFetch: ...


def build_url(
    symbol: str, day: date, side: str = "BID", base_url: str = DUKASCOPY_BASE_URL
) -> str:
    # Dukascopy numbers months from zero (January = "00"), a long-standing
    # quirk of the feed; using the calendar month fetches the wrong month.
    return (
        f"{base_url.rstrip('/')}/{symbol}/{day.year:04d}/{day.month - 1:02d}/"
        f"{day.day:02d}/{side}_candles_min_1.bi5"
    )


class DukascopyProvider:
    name = "dukascopy"

    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str = DUKASCOPY_BASE_URL,
        side: str = "BID",
    ) -> None:
        if side not in ("BID", "ASK"):
            raise ValueError(f"side must be BID or ASK, got {side!r}")
        self._client = client
        self._base_url = base_url
        self._side = side

    async def fetch_day(self, symbol: str, day: date) -> DayFetch:
        if symbol not in INSTRUMENTS:
            raise ValueError(f"unknown symbol {symbol!r}")
        if day.weekday() == _SATURDAY:
            return DayFetch(day, (), True, self.name)

        url = build_url(symbol, day, self._side, self._base_url)
        try:
            response = await self._client.get(url)
        except httpx.HTTPError as exc:
            raise ProviderError(f"{url}: {type(exc).__name__}: {exc}") from exc
        if response.status_code == 404:
            return DayFetch(day, (), True, self.name)
        if response.status_code != 200:
            raise ProviderError(f"{url}: HTTP {response.status_code}")
        if not response.content:
            return DayFetch(day, (), True, self.name)

        try:
            raw = lzma.decompress(response.content)
        except (lzma.LZMAError, EOFError) as exc:
            raise ProviderError(f"{url}: undecodable body ({exc})") from exc
        return _decode(raw, symbol, day, self.name, url)


def _decode(raw: bytes, symbol: str, day: date, source: str, url: str) -> DayFetch:
    if not raw:
        return DayFetch(day, (), True, source)
    if len(raw) % _RECORD.size:
        raise ProviderError(
            f"{url}: body is not a whole number of {_RECORD.size}-byte records"
        )

    scale = 10 ** INSTRUMENTS[symbol].price_decimals
    midnight = datetime(day.year, day.month, day.day, tzinfo=UTC)
    candles: list[Candle] = []
    dropped = 0
    for seconds, o, c, lo, h, volume in _RECORD.iter_unpack(raw):
        if not 0 <= seconds < _SECONDS_PER_DAY or seconds % 60:
            raise ProviderError(f"{url}: record offset {seconds}s is not a minute of the day")
        when = midnight + timedelta(seconds=seconds)
        # Flat zero-volume minutes during the closed window are the feed's
        # padding, not trading. Counted so the drop is visible; anything else
        # is kept as published and judged by the quality report.
        if volume == 0 and is_weekend_closed(when):
            dropped += 1
            continue
        candles.append(
            Candle(when, o / scale, h / scale, lo / scale, c / scale, float(volume))
        )
    candles.sort(key=lambda x: x.open_time)
    return DayFetch(day, tuple(candles), not candles, source, dropped)
