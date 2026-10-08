"""Public Binance klines: the lab's only network call.

Read-only market data. No API key, no signed endpoint, no account: nothing in
this module can place an order or learn anything about one.

`GET {base}/api/v3/klines?symbol=BTCUSDT&interval=15m&startTime=<ms>&limit=<n>`
answers with an array of arrays::

    [
        open_time_ms,
        "open",
        "high",
        "low",
        "close",
        "volume",
        close_time_ms,
        "quote_volume",
        trades,
        "taker_base",
        "taker_quote",
        "ignore",
    ]

Prices and volume are decimal STRINGS and are parsed straight into `Decimal`,
never through float. Times are milliseconds since the epoch and become UTC
datetimes.

## Closed versus forming

The last element of a page that reaches the present is the candle still being
built. A candle is closed when its `close_time` (its final millisecond) is
before `now`. `now` is a parameter - parsing holds no clock - so the same
payload classifies identically on replay.

## Why the default base URL is the data mirror

`api.binance.com` answers HTTP 451 from some regions. `data-api.binance.vision`
is Binance's public market-data mirror and serves the same read-only klines.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

import httpx

from app.labs.btc_range.types import SYMBOL, TIMEFRAME, Candle

#: Binance's hard maximum rows per klines request.
MAX_LIMIT = 1000
DEFAULT_TIMEOUT_SECONDS = 15.0


class KlineError(Exception):
    """The candle source answered, or failed to, in a way that cannot be used.

    Raised for a transport failure, a non-200 status or a payload that is not
    a list of well-formed kline arrays. Never swallowed into an empty list: an
    empty page means "no candles yet", and conflating the two would let an
    outage look like a quiet market.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class Kline:
    """One parsed row: the candle plus the two facts the engine's `Candle`
    deliberately omits because it only ever sees closed candles."""

    candle: Candle
    close_time: datetime
    is_closed: bool


class KlineSource(Protocol):
    async def fetch_klines(
        self, *, start: datetime | None, limit: int, now: datetime
    ) -> list[Kline]: ...


def _from_ms(value: Any, field: str) -> datetime:
    # bool is an int subclass; a JSON `true` here is malformed, not 1 ms.
    if isinstance(value, bool) or not isinstance(value, int):
        raise KlineError(f"kline {field} is not an integer: {value!r}")
    try:
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise KlineError(f"kline {field} out of range: {value!r}") from exc


def _decimal(value: Any, field: str) -> Decimal:
    if not isinstance(value, str):
        raise KlineError(f"kline {field} is not a decimal string: {value!r}")
    try:
        out = Decimal(value)
    except InvalidOperation as exc:
        raise KlineError(f"kline {field} is not a number: {value!r}") from exc
    if not out.is_finite():
        raise KlineError(f"kline {field} is not finite: {value!r}")
    return out


def parse_klines(payload: Any, *, now: datetime) -> list[Kline]:
    """Parse a klines response body. Raises `KlineError` on anything unexpected.

    The result keeps the source's order (ascending by open time).
    """
    if not isinstance(payload, list):
        # Binance reports errors as `{"code": -1121, "msg": "..."}` - often
        # with a 200 from a proxy - so a dict is an error, not an empty page.
        raise KlineError(f"klines payload is not a list: {type(payload).__name__}")
    out: list[Kline] = []
    for index, row in enumerate(payload):
        if not isinstance(row, list) or len(row) < 7:
            raise KlineError(f"kline #{index} is not an array of at least 7 fields")
        open_time = _from_ms(row[0], "open_time")
        close_time = _from_ms(row[6], "close_time")
        if close_time < open_time:
            raise KlineError(f"kline #{index} closes before it opens")
        open_, high, low, close, volume = (
            _decimal(row[1], "open"),
            _decimal(row[2], "high"),
            _decimal(row[3], "low"),
            _decimal(row[4], "close"),
            _decimal(row[5], "volume"),
        )
        out.append(
            Kline(
                candle=Candle(
                    open_time=open_time,
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                ),
                close_time=close_time,
                is_closed=close_time < now,
            )
        )
    return out


class BinanceKlineClient:
    """Thin async client over the public klines endpoint.

    Pass `http` to supply a transport (tests use `httpx.MockTransport`). A
    client it creates itself is closed by `aclose`; one passed in is the
    caller's to close.
    """

    def __init__(
        self,
        base_url: str,
        *,
        http: httpx.AsyncClient | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> BinanceKlineClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def fetch_klines(
        self, *, start: datetime | None, limit: int = MAX_LIMIT, now: datetime
    ) -> list[Kline]:
        if not 1 <= limit <= MAX_LIMIT:
            raise ValueError(f"limit must be 1..{MAX_LIMIT}, got {limit}")
        params: dict[str, str | int] = {
            "symbol": SYMBOL,
            "interval": TIMEFRAME,
            "limit": limit,
        }
        if start is not None:
            params["startTime"] = int(start.timestamp() * 1000)
        try:
            response = await self._http.get(f"{self._base_url}/api/v3/klines", params=params)
        except httpx.HTTPError as exc:
            raise KlineError(f"klines request failed: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise KlineError(
                f"klines returned HTTP {response.status_code}",
                status_code=response.status_code,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise KlineError("klines body is not JSON") from exc
        return parse_klines(payload, now=now)
