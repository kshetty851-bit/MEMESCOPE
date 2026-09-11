"""A `BreakoutSource` stand-in that never opens a socket, plus builders for
the two sources' payload shapes — copied from live responses, not invented."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.labs.breakout import config

NOW = datetime(2026, 9, 11, 2, 20, 0, tzinfo=UTC)
WSOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def gecko_pool(
    *, mint: str = "MintAAA", symbol: str = "AAA", name: str = "Token A",
    pool: str = "PoolAAA", dex: str = "raydium", age_days: float = 30.0,
    liquidity: float = 250_000.0, volume: float = 900_000.0, price: float = 0.0421,
    fdv: float = 12_000_000.0, created: datetime | None = None, now: datetime = NOW,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """One `/networks/solana/pools` row and its `included` base token."""
    created = created or now - timedelta(days=age_days)
    token_id = f"solana_{mint}"
    return (
        {
            "id": f"solana_{pool}", "type": "pool",
            "attributes": {
                "address": pool, "name": f"{symbol} / SOL",
                "pool_created_at": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "base_token_price_usd": str(price), "fdv_usd": str(fdv),
                "reserve_in_usd": str(liquidity),
                "volume_usd": {"h24": str(volume), "h1": "1000"},
            },
            "relationships": {
                "base_token": {"data": {"id": token_id, "type": "token"}},
                "quote_token": {"data": {"id": f"solana_{WSOL}", "type": "token"}},
                "dex": {"data": {"id": dex, "type": "dex"}},
            },
        },
        {"id": token_id, "type": "token",
         "attributes": {"address": mint, "name": name, "symbol": symbol, "decimals": 6}},
    )


def gecko_body(*pools: tuple[dict[str, Any], dict[str, Any]]) -> dict[str, Any]:
    included = {token["id"]: token for _, token in pools}
    return {"data": [pool for pool, _ in pools], "included": list(included.values())}


def dex_pair(
    *, mint: str = "MintDDD", symbol: str = "DDD", name: str = "Token D",
    pool: str = "PoolDDD", dex: str = "meteora", age_days: float = 40.0,
    liquidity: float | None = 180_000.0, volume: float = 400_000.0,
    price: str = "0.0072", now: datetime = NOW, chain: str = "solana",
) -> dict[str, Any]:
    """One `/tokens/v1/solana/{mints}` row. `liquidity=None` reproduces the
    documented bonding-curve gap, where the key is absent entirely."""
    pair: dict[str, Any] = {
        "chainId": chain, "dexId": dex, "pairAddress": pool,
        "baseToken": {"address": mint, "name": name, "symbol": symbol},
        "quoteToken": {"address": WSOL, "name": "Wrapped SOL", "symbol": "SOL"},
        "priceUsd": price, "volume": {"h24": volume}, "fdv": 5_000_000.0,
        "pairCreatedAt": int((now - timedelta(days=age_days)).timestamp() * 1000),
    }
    if liquidity is not None:
        pair["liquidity"] = {"usd": liquidity, "base": 1, "quote": 2}
    return pair


def ohlcv(
    timeframe: str, *, bars: int, newest_open: datetime, price: float = 100.0,
) -> list[list[Any]]:
    """`bars` rows NEWEST FIRST, as GeckoTerminal serves them."""
    step = config.INTERVAL_SECONDS[timeframe]
    newest = int(newest_open.timestamp())
    return [
        [newest - i * step, price + i, price + i + 2, price + i - 2, price + i + 1,
         1_000.0 + i]
        for i in range(bars)
    ]


class FakeSource:
    """Records every call. `fail_pools` raises for a pool; `statuses` lets a
    test drive a 429 storm through the real budget code instead of this."""

    def __init__(self, *, pages=None, trending=None, boosts=None, profiles=None,
                 pairs=None, ohlcv_by=None, fail_pools=(), max_calls=10_000,
                 dex_pages=None) -> None:
        self.pages = pages or {}
        #: (dex, page) -> a `/dexes/{dex}/pools` body.
        self.dex_pages: dict[tuple[str, int], Any] = dex_pages or {}
        self.trending = trending or {"data": [], "included": []}
        self.boosts = boosts or []
        self.profiles = profiles or []
        self.pairs = pairs or []
        #: (pool, timeframe) -> list of rows, newest first, the WHOLE history.
        self.ohlcv_by: dict[tuple[str, str], list[list[Any]]] = ohlcv_by or {}
        self.fail_pools = set(fail_pools)
        self.requests = {"geckoterminal": 0, "dexscreener": 0}
        self.calls: list[Any] = []
        self._max_calls = max_calls

    @property
    def total_requests(self) -> int:
        return sum(self.requests.values())

    def _spend(self, host: str) -> None:
        from app.labs.breakout.sources import BudgetExhaustedError

        if self.total_requests >= self._max_calls:
            raise BudgetExhaustedError("fake budget spent")
        self.requests[host] += 1

    async def gecko_pools(self, page, sort="h24_volume_usd_desc"):
        self._spend("geckoterminal")
        self.calls.append(("pools", page))
        # Keyed by page only: a test that wants two sorts to differ can pass
        # `dex_pages`, and every existing test reads the same page whichever
        # sort asked for it.
        return self.pages.get(page, {"data": [], "included": []})

    async def gecko_dex_pools(self, dex, page):
        self._spend("geckoterminal")
        self.calls.append(("dex_pools", dex, page))
        return self.dex_pages.get((dex, page), {"data": [], "included": []})

    async def gecko_trending(self):
        self._spend("geckoterminal")
        self.calls.append(("trending",))
        return self.trending

    async def gecko_ohlcv(self, pool, timeframe, *, limit=config.OHLCV_LIMIT, before=None):
        self._spend("geckoterminal")
        self.calls.append(("ohlcv", pool, timeframe, limit, before))
        if pool in self.fail_pools:
            raise RuntimeError(f"fake failure for {pool}")
        rows = self.ohlcv_by.get((pool, timeframe), [])
        if before is not None:  # inclusive, exactly as the API behaves
            rows = [r for r in rows if r[0] <= before]
        return rows[:min(limit, config.OHLCV_LIMIT)]

    async def dex_boosts(self):
        self._spend("dexscreener")
        self.calls.append(("boosts",))
        return self.boosts

    async def dex_profiles(self):
        self._spend("dexscreener")
        self.calls.append(("profiles",))
        return self.profiles

    async def dex_pairs(self, mints):
        self._spend("dexscreener")
        self.calls.append(("pairs", tuple(mints)))
        wanted = set(mints)
        return [p for p in self.pairs if p["baseToken"]["address"] in wanted]
