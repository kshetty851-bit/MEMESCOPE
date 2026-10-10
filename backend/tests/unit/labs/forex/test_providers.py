"""Dukascopy provider: URL scheme, bi5 decoding and failure semantics.

No network: a synthetic .bi5 body is served through `httpx.MockTransport`.
The shared property: the provider returns what the feed published, says so when
the feed published nothing, and raises when it cannot tell the difference —
a failed day must never look like an empty one.
"""

from __future__ import annotations

import lzma
import struct
from collections.abc import Callable
from datetime import UTC, date, datetime

import httpx
import pytest

from app.labs.forex.providers import (
    PROVIDERS_INFO,
    CandleProvider,
    DukascopyProvider,
    ProviderError,
    build_url,
)

pytestmark = pytest.mark.unit

TUE = date(2024, 3, 5)
FRI = date(2024, 3, 8)
SAT = date(2024, 3, 9)
SUN = date(2024, 3, 3)

Record = tuple[int, int, int, int, int, float]  # seconds, open, close, low, high, volume


def bi5(records: list[Record]) -> bytes:
    raw = b"".join(struct.pack(">5if", *r) for r in records)
    return lzma.compress(raw, format=lzma.FORMAT_ALONE)


def provider(
    handler: Callable[[httpx.Request], httpx.Response], **kw: str
) -> tuple[DukascopyProvider, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return DukascopyProvider(client, **kw), client


def serving(body: bytes, status: int = 200) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(status, content=body)


class TestBuildUrl:
    def test_month_is_zero_based_and_day_is_two_digits(self) -> None:
        """Dukascopy counts months from 00; the calendar month would fetch the wrong file."""
        assert build_url("EURUSD", date(2024, 1, 5), "BID") == (
            "https://datafeed.dukascopy.com/datafeed/EURUSD/2024/00/05/BID_candles_min_1.bi5"
        )
        assert build_url("GBPUSD", date(2023, 12, 31), "ASK").endswith(
            "/GBPUSD/2023/11/31/ASK_candles_min_1.bi5"
        )

    def test_base_url_trailing_slash_is_tolerated(self) -> None:
        url = build_url("EURUSD", TUE, "BID", "https://example.test/feed/")
        assert url == "https://example.test/feed/EURUSD/2024/02/05/BID_candles_min_1.bi5"


class TestDecode:
    async def test_fields_are_read_in_open_close_low_high_order(self) -> None:
        """The wire order is (open, close, low, high), not OHLC; mixing it up swaps real prices."""
        body = bi5(
            [
                (0, 110429, 110428, 110425, 110430, 12.5),
                (60, 110428, 110440, 110420, 110445, 3.0),
            ]
        )
        p, client = provider(serving(body))
        async with client:
            r = await p.fetch_day("EURUSD", TUE)
        first, second = r.candles
        assert (first.open, first.high, first.low, first.close) == (
            1.10429,
            1.1043,
            1.10425,
            1.10428,
        )
        assert first.volume == 12.5
        assert first.open_time == datetime(2024, 3, 5, 0, 0, tzinfo=UTC)
        assert second.open_time == datetime(2024, 3, 5, 0, 1, tzinfo=UTC)
        assert (second.close, second.low, second.high) == (1.1044, 1.1042, 1.10445)
        assert (r.empty, r.source, r.dropped_flat, r.day) == (False, "dukascopy", 0, TUE)

    async def test_jpy_pairs_use_three_decimals(self) -> None:
        body = bi5([(3600, 150123, 150130, 150100, 150150, 1.0)])
        p, client = provider(serving(body))
        async with client:
            r = await p.fetch_day("USDJPY", TUE)
        c = r.candles[0]
        assert (c.open, c.high, c.low, c.close) == (150.123, 150.15, 150.1, 150.13)
        assert c.open_time == datetime(2024, 3, 5, 1, 0, tzinfo=UTC)

    async def test_request_goes_to_the_documented_path(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, content=bi5([(0, 1, 1, 1, 1, 1.0)]))

        p, client = provider(handler)
        async with client:
            await p.fetch_day("EURUSD", TUE)
        assert seen == [
            "https://datafeed.dukascopy.com/datafeed/EURUSD/2024/02/05/BID_candles_min_1.bi5"
        ]

    async def test_ask_side_and_custom_base_url_are_honoured(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(404)

        p, client = provider(handler, base_url="https://mirror.test/x", side="ASK")
        async with client:
            await p.fetch_day("EURUSD", TUE)
        assert seen == ["https://mirror.test/x/EURUSD/2024/02/05/ASK_candles_min_1.bi5"]

    async def test_prices_are_not_modified_beyond_scaling(self) -> None:
        records = [
            (60 * i, 110000 + i, 110000 + 2 * i, 109990, 110100 + i, 1.0) for i in range(30)
        ]
        p, client = provider(serving(bi5(records)))
        async with client:
            r = await p.fetch_day("EURUSD", TUE)
        assert [c.open for c in r.candles] == [(110000 + i) / 100000 for i in range(30)]
        assert [c.close for c in r.candles] == [(110000 + 2 * i) / 100000 for i in range(30)]


class TestEmptyVersusFailed:
    async def test_404_is_an_empty_day(self) -> None:
        p, client = provider(serving(b"", 404))
        async with client:
            r = await p.fetch_day("EURUSD", TUE)
        assert (r.empty, r.candles, r.day) == (True, (), TUE)

    async def test_zero_length_body_is_an_empty_day(self) -> None:
        p, client = provider(serving(b""))
        async with client:
            assert (await p.fetch_day("EURUSD", TUE)).empty

    async def test_compressed_empty_payload_is_an_empty_day(self) -> None:
        p, client = provider(serving(lzma.compress(b"", format=lzma.FORMAT_ALONE)))
        async with client:
            assert (await p.fetch_day("EURUSD", TUE)).empty

    @pytest.mark.parametrize("status", [500, 502, 503, 429, 403])
    async def test_other_http_errors_raise_so_the_day_is_retried_not_recorded_empty(
        self, status: int
    ) -> None:
        p, client = provider(serving(b"oops", status))
        async with client:
            with pytest.raises(ProviderError, match=str(status)):
                await p.fetch_day("EURUSD", TUE)

    async def test_corrupt_body_raises(self) -> None:
        p, client = provider(serving(b"this is definitely not lzma data at all, no sir"))
        async with client:
            with pytest.raises(ProviderError):
                await p.fetch_day("EURUSD", TUE)

    async def test_truncated_stream_raises(self) -> None:
        body = bi5([(60 * i, 110000, 110000, 110000, 110000, 1.0) for i in range(500)])
        p, client = provider(serving(body[: len(body) // 2]))
        async with client:
            with pytest.raises(ProviderError):
                await p.fetch_day("EURUSD", TUE)

    async def test_payload_that_is_not_whole_records_raises(self) -> None:
        body = lzma.compress(b"\x00" * 25, format=lzma.FORMAT_ALONE)
        p, client = provider(serving(body))
        async with client:
            with pytest.raises(ProviderError, match="records"):
                await p.fetch_day("EURUSD", TUE)

    @pytest.mark.parametrize("seconds", [86_400, -60, 61])
    async def test_record_time_outside_the_day_or_off_the_minute_raises(
        self, seconds: int
    ) -> None:
        p, client = provider(serving(bi5([(seconds, 1, 1, 1, 1, 1.0)])))
        async with client:
            with pytest.raises(ProviderError):
                await p.fetch_day("EURUSD", TUE)

    async def test_transport_failure_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=request)

        p, client = provider(handler)
        async with client:
            with pytest.raises(ProviderError):
                await p.fetch_day("EURUSD", TUE)


class TestWeekendHandling:
    async def test_saturday_is_answered_without_a_request(self) -> None:
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, content=b"")

        p, client = provider(handler)
        async with client:
            r = await p.fetch_day("EURUSD", SAT)
        assert calls == []
        assert (r.empty, r.candles, r.day, r.source) == (True, (), SAT, "dukascopy")

    async def test_flat_zero_volume_minutes_in_the_closed_window_are_dropped_and_counted(
        self,
    ) -> None:
        """Sunday before 22:00 UTC is closed in the lab's model; padding there is not trading."""
        body = bi5(
            [
                (21 * 3600, 110000, 110000, 110000, 110000, 0.0),  # closed, flat: drop
                (21 * 3600 + 60, 110000, 110000, 110000, 110000, 0.0),  # closed, flat: drop
                (
                    21 * 3600 + 120,
                    110000,
                    110010,
                    109990,
                    110020,
                    4.0,
                ),  # closed but real: keep
                (22 * 3600, 110010, 110010, 110010, 110010, 0.0),  # open, zero volume: keep
                (22 * 3600 + 60, 110010, 110020, 110000, 110030, 2.0),
            ]
        )
        p, client = provider(serving(body))
        async with client:
            r = await p.fetch_day("EURUSD", SUN)
        assert r.dropped_flat == 2
        assert [(c.open_time.hour, c.open_time.minute) for c in r.candles] == [
            (21, 2),
            (22, 0),
            (22, 1),
        ]
        assert r.empty is False

    async def test_friday_evening_padding_is_dropped_but_friday_trading_is_not(self) -> None:
        body = bi5(
            [
                (20 * 3600 + 59 * 60, 110000, 110001, 109999, 110002, 5.0),
                (21 * 3600, 110001, 110001, 110001, 110001, 0.0),
                (23 * 3600, 110001, 110001, 110001, 110001, 0.0),
            ]
        )
        p, client = provider(serving(body))
        async with client:
            r = await p.fetch_day("EURUSD", FRI)
        assert r.dropped_flat == 2
        assert len(r.candles) == 1 and r.candles[0].open_time.hour == 20

    async def test_a_day_that_is_all_padding_is_empty_and_says_how_much_was_dropped(
        self,
    ) -> None:
        body = bi5(
            [(23 * 3600 + 60 * i, 110000, 110000, 110000, 110000, 0.0) for i in range(5)]
        )
        p, client = provider(serving(body))
        async with client:
            r = await p.fetch_day("EURUSD", FRI)
        assert (r.empty, r.candles, r.dropped_flat) == (True, (), 5)


class TestSetup:
    def test_invalid_side_is_refused(self) -> None:
        with pytest.raises(ValueError):
            DukascopyProvider(httpx.AsyncClient(), side="MID")

    async def test_unknown_symbol_is_refused_before_any_request(self) -> None:
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(404)

        p, client = provider(handler)
        async with client:
            with pytest.raises(ValueError):
                await p.fetch_day("XAUUSD", TUE)
        assert calls == []

    def test_satisfies_the_provider_protocol(self) -> None:
        p: CandleProvider = DukascopyProvider(httpx.AsyncClient())
        assert p.name == "dukascopy"

    def test_provider_info_describes_both_sources(self) -> None:
        assert set(PROVIDERS_INFO) == {"dukascopy", "csv"}
        assert PROVIDERS_INFO["dukascopy"]["cost"] == "free"
        assert PROVIDERS_INFO["dukascopy"]["price_side"] == "BID"
        assert PROVIDERS_INFO["dukascopy"]["url"].startswith("https://")
        assert all(
            isinstance(v, str) for info in PROVIDERS_INFO.values() for v in info.values()
        )
