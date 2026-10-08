"""The candle source: what it parses, and what it refuses to guess.

The sandbox cannot reach Binance, so every request goes through
`httpx.MockTransport` with a payload hand-written in Binance's real shape.
What matters is the property, not the transport: prices stay exact decimals, a
candle is closed only once its last millisecond has passed, and an outage or a
malformed body is an ERROR - never an empty page that reads as a quiet market.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from app.labs.btc_range.source import BinanceKlineClient, KlineError, parse_klines

pytestmark = pytest.mark.unit

T0 = datetime(2026, 10, 8, 0, 0, tzinfo=UTC)
STEP = timedelta(minutes=15)


def _ms(at: datetime) -> int:
    return int(at.timestamp() * 1000)


def kline(
    open_time: datetime,
    o="62100.10",
    h="62150.00",
    low="62080.55",
    c="62120.30",
    v="12.34567000",
) -> list:
    """Binance's 12-field kline array, with its real types (ints and strings)."""
    return [
        _ms(open_time),
        o,
        h,
        low,
        c,
        v,
        _ms(open_time + STEP) - 1,  # close time: the candle's last millisecond
        "766801.12345678",
        1523,
        "6.1",
        "379000.5",
        "0",
    ]


def client(handler) -> BinanceKlineClient:
    return BinanceKlineClient(
        "https://data-api.binance.vision/",
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


# --- parsing ----------------------------------------------------------------


def test_prices_are_exact_decimals_and_times_are_utc() -> None:
    (k,) = parse_klines([kline(T0)], now=T0 + timedelta(hours=1))
    assert k.candle.open == Decimal("62100.10")
    assert k.candle.high == Decimal("62150.00")
    assert k.candle.low == Decimal("62080.55")
    assert k.candle.close == Decimal("62120.30")
    assert k.candle.volume == Decimal("12.34567000")
    assert k.candle.open_time == T0
    assert k.candle.open_time.utcoffset() == timedelta(0)
    assert k.close_time == T0 + STEP - timedelta(milliseconds=1)


def test_a_float_never_touches_a_price() -> None:
    """0.1 + 0.2 style drift would put a different number in the record."""
    (k,) = parse_klines([kline(T0, o="0.10000001")], now=T0 + timedelta(hours=1))
    assert k.candle.open == Decimal("0.10000001")


def test_candle_is_closed_only_after_its_last_millisecond() -> None:
    row = kline(T0)
    close_time = T0 + STEP - timedelta(milliseconds=1)
    assert parse_klines([row], now=close_time)[0].is_closed is False  # not strictly before
    assert parse_klines([row], now=close_time + timedelta(milliseconds=1))[0].is_closed is True
    assert parse_klines([row], now=T0 + timedelta(minutes=7))[0].is_closed is False


def test_closed_and_forming_are_decided_per_row() -> None:
    now = T0 + 2 * STEP + timedelta(minutes=3)
    rows = [kline(T0), kline(T0 + STEP), kline(T0 + 2 * STEP)]
    assert [k.is_closed for k in parse_klines(rows, now=now)] == [True, True, False]


def test_order_is_preserved() -> None:
    rows = [kline(T0 + i * STEP) for i in range(3)]
    parsed = parse_klines(rows, now=T0 + timedelta(days=1))
    assert [k.candle.open_time for k in parsed] == [T0 + i * STEP for i in range(3)]


def test_an_empty_page_is_empty_not_an_error() -> None:
    assert parse_klines([], now=T0) == []


@pytest.mark.parametrize(
    "payload",
    [
        {"code": -1121, "msg": "Invalid symbol."},  # Binance's error shape
        "nope",
        None,
        [["not", "enough"]],
        ["a string, not an array"],
        [[_ms(T0), "1", "2", "0.5", "1.5", "x", _ms(T0) + 1]],  # non-numeric volume
        [[_ms(T0), 1, "2", "0.5", "1.5", "3", _ms(T0) + 1]],  # price not a string
        [[_ms(T0), "NaN", "2", "0.5", "1.5", "3", _ms(T0) + 1]],
        [[_ms(T0), "Infinity", "2", "0.5", "1.5", "3", _ms(T0) + 1]],
        [["1700000000000", "1", "2", "0.5", "1.5", "3", _ms(T0)]],  # open_time as str
        [[True, "1", "2", "0.5", "1.5", "3", _ms(T0)]],
        [[_ms(T0), "1", "2", "0.5", "1.5", "3", _ms(T0) - 1]],  # closes before opening
    ],
)
def test_malformed_payloads_raise_a_typed_error(payload) -> None:
    with pytest.raises(KlineError):
        parse_klines(payload, now=T0)


# --- the client -------------------------------------------------------------


async def test_request_shape_is_the_public_klines_endpoint() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[kline(T0)])

    out = await client(handler).fetch_klines(start=T0, limit=500, now=T0 + timedelta(hours=1))

    assert len(out) == 1
    (request,) = seen
    assert request.method == "GET"
    assert str(request.url).startswith("https://data-api.binance.vision/api/v3/klines?")
    params = dict(request.url.params)
    assert params == {
        "symbol": "BTCUSDT",
        "interval": "15m",
        "limit": "500",
        "startTime": str(_ms(T0)),
    }
    # Read-only market data: nothing that identifies an account or signs.
    assert not {"x-mbx-apikey", "authorization"} & {h.lower() for h in request.headers}
    assert "signature" not in params and "timestamp" not in params


async def test_start_time_is_omitted_when_not_given() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    await client(handler).fetch_klines(start=None, limit=10, now=T0)
    assert "startTime" not in seen[0].url.params


@pytest.mark.parametrize("status", [400, 418, 429, 451, 500, 503])
async def test_a_non_200_is_an_error_carrying_the_status(status: int) -> None:
    c = client(lambda r: httpx.Response(status, json={"code": -1003, "msg": "x"}))
    with pytest.raises(KlineError) as exc:
        await c.fetch_klines(start=T0, limit=10, now=T0)
    assert exc.value.status_code == status


async def test_a_non_json_body_is_an_error() -> None:
    c = client(lambda r: httpx.Response(200, content=b"<html>blocked</html>"))
    with pytest.raises(KlineError):
        await c.fetch_klines(start=T0, limit=10, now=T0)


async def test_a_transport_failure_is_an_error_not_an_empty_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    with pytest.raises(KlineError):
        await client(handler).fetch_klines(start=T0, limit=10, now=T0)


async def test_a_dict_body_with_200_is_an_error() -> None:
    c = client(lambda r: httpx.Response(200, content=json.dumps({"msg": "bad"})))
    with pytest.raises(KlineError):
        await c.fetch_klines(start=T0, limit=10, now=T0)


@pytest.mark.parametrize("limit", [0, 1001, -1])
async def test_limit_is_bounded_to_binances_maximum(limit: int) -> None:
    with pytest.raises(ValueError):
        await client(lambda r: httpx.Response(200, json=[])).fetch_klines(
            start=T0, limit=limit, now=T0
        )
