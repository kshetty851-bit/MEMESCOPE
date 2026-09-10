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
                 fail_symbols=(), charts=None) -> None:
        self.markets = MARKETS if markets is None else markets
        #: coingecko id -> [[ts_ms, market_cap], ...]
        self.charts = charts or {}
        self.perps = PERPS if perps is None else perps
        self.klines_by: dict[tuple[str, str], list[list[Any]]] = klines or {}
        self.premium_rows = premium_rows or []
        self.fail_symbols = set(fail_symbols)
        self.requests = 0
        self.calls: list[Any] = []

    async def coingecko_markets(self, per_page=None):
        self.requests += 1
        self.calls.append(("markets", per_page))
        return self.markets[:per_page] if per_page else self.markets

    async def coingecko_market_chart(self, coin_id, *, days):
        self.requests += 1
        self.calls.append(("chart", coin_id, days))
        return self.charts.get(coin_id, [])

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


# --- Phase 2: synthetic candle series ------------------------------------------
#
# Deterministic integer paths so swing detection is exact: a sawtooth that
# climbs 10 bars and falls 4 (net +6 a cycle) makes every peak a higher high
# and every trough a higher low under a 5-bar lookback; its mirror makes
# LH_LL; an integer triangle wave repeats the SAME peak, which the strict
# comparison classifies as MIXED. Wicks depend on bar direction so a peak's
# high is never equalled by the next bar's high.

def uptrend_closes(n: int, *, start: float = 100.0, up: int = 10,
                   down: int = 4) -> list[float]:
    out, price = [], start
    for i in range(n):
        price += 1.0 if i % (up + down) < up else -1.0
        out.append(price)
    return out


def downtrend_closes(n: int, *, start: float = 300.0, up: int = 10,
                     down: int = 4) -> list[float]:
    return [2 * start - p for p in uptrend_closes(n, start=start, up=up, down=down)]


def sideways_closes(n: int, *, centre: float = 100.0) -> list[float]:
    wave = [0, 1, 2, 3, 2, 1, 0, -1, -2, -3, -2, -1]
    return [centre + wave[i % len(wave)] for i in range(n)]


def synthetic_candles(closes, *, symbol: str = "BTCUSDT", timeframe: str = "1h",
                      end_ms: int = NOW_MS):
    """Candles from a close path, the last one closing just before `end_ms`."""
    from decimal import Decimal

    from app.labs.crypto_trend.candles import Candle, from_ms

    interval = INTERVAL_MS[timeframe]
    first_open = (end_ms // interval) * interval - len(closes) * interval
    out, prev = [], closes[0]
    for i, close in enumerate(closes):
        open_ = prev
        if close > open_:
            high, low = close + 0.3, open_ - 0.1
        elif close < open_:
            high, low = open_ + 0.1, close - 0.3
        else:
            high, low = close + 0.1, close - 0.1
        open_ms = first_open + i * interval
        out.append(Candle(symbol, timeframe, from_ms(open_ms), Decimal(str(open_)),
                          Decimal(str(high)), Decimal(str(low)), Decimal(str(close)),
                          Decimal("1"), from_ms(open_ms + interval - 1)))
        prev = close
    return out


def with_pullback(closes, *, dip_to: float, rebound: int) -> list[float]:
    """`closes`, then a one-per-bar descent landing exactly on `dip_to`, then a
    one-per-bar climb for `rebound` bars."""
    out, price = list(closes), closes[-1]
    while price > dip_to:
        price = max(price - 1.0, dip_to)
        out.append(price)
    for _ in range(rebound):
        price += 1.0
        out.append(price)
    return out


def then_dip(closes, bars: int) -> list[float]:
    """`closes`, then `bars` bars falling one each — enough to confirm the
    last peak as a swing high without confirming a new low."""
    out, price = list(closes), closes[-1]
    for _ in range(bars):
        price -= 1.0
        out.append(price)
    return out
