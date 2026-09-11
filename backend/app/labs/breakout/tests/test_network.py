"""The one test that talks to GeckoTerminal. Off unless `RUN_NETWORK_TESTS`."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from itertools import pairwise

import pytest

from app.labs.breakout.candles import interval, parse_ohlcv
from app.labs.breakout.sources import BreakoutSource

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_NETWORK_TESTS"),
    reason="set RUN_NETWORK_TESTS=1 to hit GeckoTerminal")

#: Raydium's SOL/USDC AMM — the deepest, oldest pool on the network, so it is
#: the one pool whose history is certain to exist.
SOL_USDC_RAYDIUM = "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2"


async def test_five_daily_candles_for_the_sol_usdc_raydium_pool() -> None:
    async with BreakoutSource() as source:
        rows = await source.gecko_ohlcv(SOL_USDC_RAYDIUM, "day", limit=5)
    assert len(rows) == 5

    opens = [int(r[0]) for r in rows]
    assert opens == sorted(opens, reverse=True), "the API serves newest first"
    step = int(interval("day").total_seconds())
    assert all(a - b == step for a, b in pairwise(opens))

    now = datetime.now(UTC)
    candles = parse_ohlcv("SOL", SOL_USDC_RAYDIUM, "day", rows, now=now)
    assert 4 <= len(candles) <= 5, "the newest bar is the one still forming"
    for candle in candles:
        assert candle.low <= candle.open <= candle.high
        assert candle.low <= candle.close <= candle.high
        assert candle.close_time <= now
        assert candle.close_time - candle.open_time == interval("day")
        # SOL has never been worth a cent or ten thousand dollars.
        assert 1 < float(candle.close) < 10_000
