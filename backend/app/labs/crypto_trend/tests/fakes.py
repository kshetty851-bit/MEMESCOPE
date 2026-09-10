"""A `MarketSource` stand-in that never opens a socket."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.labs.crypto_trend.candles import INTERVAL_MS, to_ms

NOW = datetime(2026, 9, 10, 12, 0, 30, tzinfo=UTC)
NOW_MS = to_ms(NOW)

MARKETS: list[dict[str, Any]] = [
    {"id": "bitcoin", "symbol": "btc", "name": "Bitcoin",
     "market_cap": 1_545_300_000_000, "market_cap_rank": 1},
    {"id": "tether", "symbol": "usdt", "name": "Tether",
     "market_cap": 183_400_000_000, "market_cap_rank": 3},
    {"id": "ethereum", "symbol": "eth", "name": "Ethereum",
     "market_cap": 296_000_000_000, "market_cap_rank": 2},
    {"id": "figure-heloc", "symbol": "figr_heloc", "name": "Figure Heloc",
     "market_cap": 23_000_000_000, "market_cap_rank": 9},
]
PERPS = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "USDCUSDT"}


def kline(open_ms: int, interval_ms: int, close: str = "100.5") -> list[Any]:
    """One Binance kline row: the 12-field shape, close_time = open + interval - 1."""
    return [open_ms, "100.0", "101.0", "99.0", close, "12.5", open_ms + interval_ms - 1,
            "1250.0", 42, "6.0", "600.0", "0"]


def klines_ending_at(timeframe: str, now_ms: int, closed: int) -> list[list[Any]]:
    """`closed` closed candles before `now_ms`, plus the one still forming."""
    interval = INTERVAL_MS[timeframe]
    current_open = (now_ms // interval) * interval
    first = current_open - closed * interval
    return [kline(first + i * interval, interval, close=str(100 + i))
            for i in range(closed + 1)]


def premium(symbol: str, rate: str = "0.0001", next_ms: int = NOW_MS + 3_600_000) -> dict:
    return {"symbol": symbol, "markPrice": "100.25", "lastFundingRate": rate,
            "nextFundingTime": next_ms, "time": NOW_MS}


class FakeSource:
    def __init__(self, *, markets=None, perps=None, klines=None, premium_rows=None,
                 fail_symbols=()) -> None:
        self.markets = MARKETS if markets is None else markets
        self.perps = PERPS if perps is None else perps
        self.klines_by: dict[tuple[str, str], list[list[Any]]] = klines or {}
        self.premium_rows = premium_rows or []
        self.fail_symbols = set(fail_symbols)
        self.requests = 0
        self.calls: list[Any] = []

    async def coingecko_markets(self):
        self.requests += 1
        self.calls.append("markets")
        return self.markets

    async def binance_perps(self):
        self.requests += 1
        self.calls.append("perps")
        return set(self.perps)

    async def klines(self, symbol, interval, *, start_ms=None, limit=1000):
        self.requests += 1
        self.calls.append(("klines", symbol, interval, start_ms))
        if symbol in self.fail_symbols:
            raise RuntimeError(f"simulated failure for {symbol}")
        rows = self.klines_by.get((symbol, interval), [])
        return [r for r in rows if start_ms is None or r[0] >= start_ms][:limit]

    async def premium_index(self):
        self.requests += 1
        self.calls.append("premium")
        return self.premium_rows
