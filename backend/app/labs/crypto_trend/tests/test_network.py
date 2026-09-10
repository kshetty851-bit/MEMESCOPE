"""The one test that talks to Binance. Off unless `RUN_NETWORK_TESTS` is set."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from itertools import pairwise

import pytest

from app.labs.crypto_trend.candles import INTERVAL_MS, parse_klines, to_ms
from app.labs.crypto_trend.sources import MarketSource

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_NETWORK_TESTS"), reason="set RUN_NETWORK_TESTS=1 to hit Binance")


async def test_fetch_five_btcusdt_hourly_candles() -> None:
    async with MarketSource() as source:
        rows = await source.klines("BTCUSDT", "1h", limit=5)
    assert len(rows) == 5
    opens = [int(r[0]) for r in rows]
    assert all(b - a == INTERVAL_MS["1h"] for a, b in pairwise(opens))

    candles = parse_klines("BTCUSDT", "1h", rows, now_ms=to_ms(datetime.now(UTC)))
    assert 4 <= len(candles) <= 5  # the newest row is usually still forming
    for c in candles:
        assert c.low <= c.open <= c.high
        assert c.low <= c.close <= c.high
        assert c.volume > 0
        assert to_ms(c.close_time) - to_ms(c.open_time) == INTERVAL_MS["1h"] - 1
