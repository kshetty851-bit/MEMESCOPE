"""The HTTP layer with the network mocked at the transport."""

from __future__ import annotations

import httpx
import pytest

from app.core.backoff import BackoffPolicy
from app.labs.crypto_trend import config
from app.labs.crypto_trend.sources import MarketSource, klines_weight
from app.services.market.providers.rate_budget import CallBudget


def make_source(handler, *, budget=None, clock=None):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if clock is not None:
            clock[0] += 30.0

    source = MarketSource(
        client=client, budget=budget or CallBudget(10_000),
        backoff=BackoffPolicy(initial_seconds=1.0, max_seconds=30.0, jitter=False),
        sleep=sleep)
    return source, sleeps


async def test_429_honours_retry_after_then_succeeds() -> None:
    seen = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen
        seen += 1
        if seen == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, json=[[0, "1", "1", "1", "1", "1", 3599999]])

    source, sleeps = make_source(handler)
    async with source:
        rows = await source.klines("BTCUSDT", "1h", limit=5)
    assert len(rows) == 1
    assert sleeps == [7.0]
    assert source.requests == 2


async def test_418_without_retry_after_backs_off_exponentially() -> None:
    statuses = iter([418, 418, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        status = next(statuses)
        return httpx.Response(status, json=[] if status == 200 else None)

    source, sleeps = make_source(handler)
    async with source:
        await source.klines("BTCUSDT", "1h", limit=5)
    assert sleeps == [1.0, 2.0]


async def test_gives_up_after_max_attempts() -> None:
    source, sleeps = make_source(lambda request: httpx.Response(503))
    async with source:
        with pytest.raises(RuntimeError, match="gave up"):
            await source.klines("BTCUSDT", "1h", limit=5)
    assert source.requests == config.MAX_ATTEMPTS
    assert len(sleeps) == config.MAX_ATTEMPTS


async def test_a_4xx_other_than_429_is_not_retried() -> None:
    source, sleeps = make_source(lambda request: httpx.Response(400, json={"code": -1121}))
    async with source:
        with pytest.raises(httpx.HTTPStatusError):
            await source.klines("NOPEUSDT", "1h", limit=5)
    assert source.requests == 1
    assert sleeps == []


async def test_weight_budget_waits_for_refill() -> None:
    """Two weight-10 calls against a 10-per-minute budget: the second waits
    until the bucket has refilled, and the wait is a sleep, not a request."""
    clock = [0.0]
    budget = CallBudget(10, window_seconds=60.0, clock=lambda: clock[0])
    source, sleeps = make_source(lambda request: httpx.Response(200, json=[]),
                                 budget=budget, clock=clock)
    async with source:
        await source.klines("BTCUSDT", "1h", limit=1000)
        await source.klines("ETHUSDT", "1h", limit=1000)
    assert source.requests == 2
    assert len(sleeps) == 2  # 30s per fake sleep, 10 tokens per 60s


def test_klines_weight_tiers_match_binance() -> None:
    tiers = [klines_weight(n) for n in (5, 99, 100, 499, 500, 999, 1000)]
    assert tiers == [1, 1, 2, 2, 5, 5, 10]


async def test_binance_perps_keeps_only_trading_usdt_perpetuals() -> None:
    info = {"symbols": [
        {"symbol": "BTCUSDT", "contractType": "PERPETUAL", "quoteAsset": "USDT",
         "status": "TRADING"},
        {"symbol": "BTCUSDT_260925", "contractType": "CURRENT_QUARTER", "quoteAsset": "USDT",
         "status": "TRADING"},
        {"symbol": "BTCUSDC", "contractType": "PERPETUAL", "quoteAsset": "USDC",
         "status": "TRADING"},
        {"symbol": "OLDUSDT", "contractType": "PERPETUAL", "quoteAsset": "USDT",
         "status": "SETTLING"},
    ]}
    source, _ = make_source(lambda request: httpx.Response(200, json=info))
    async with source:
        assert await source.binance_perps() == {"BTCUSDT"}


async def test_the_coingecko_query_is_the_one_the_brief_names() -> None:
    captured: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.url)
        return httpx.Response(200, json=[])

    source, _ = make_source(handler)
    async with source:
        await source.coingecko_markets()
    (url,) = captured
    assert str(url).startswith("https://api.coingecko.com/api/v3/coins/markets?")
    assert dict(url.params) == {"vs_currency": "usd", "order": "market_cap_desc",
                                "per_page": "30", "page": "1"}


async def test_klines_sends_start_time_only_when_given() -> None:
    captured: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.url)
        return httpx.Response(200, json=[])

    source, _ = make_source(handler)
    async with source:
        await source.klines("BTCUSDT", "4h", limit=1000)
        await source.klines("BTCUSDT", "4h", start_ms=1789045200000, limit=1000)
    assert "startTime" not in captured[0].params
    assert captured[1].params["startTime"] == "1789045200000"
    assert captured[1].params["interval"] == "4h"
