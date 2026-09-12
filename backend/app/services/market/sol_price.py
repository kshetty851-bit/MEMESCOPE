"""SOL/USD for the navigation rail: one price, one sparkline, cached.

Every screen shows it, so this is the most-requested number in the product and
the one with the least tolerance for cost. Two rules follow from that:

* **One upstream call per cache window, shared by every viewer.** The rail is
  mounted on every route, so an uncached fetch would multiply by tabs, by
  users, and by every navigation — against providers that rate-limit by IP and
  are already carrying the enrichment services on this host.
* **Stale beats absent.** If the upstream fails, the last good answer is
  served with its age attached rather than an error. A price that is ninety
  seconds old is useful; a dash is not, and a rail that flickers empty on
  every provider hiccup would be worse than no rail.

The source is the deepest SOL/USDC pool on Solana — Raydium's, at roughly $30M
against Orca's $24M — addressed by POOL rather than by mint, because a mint
lookup returns every pool it trades in and the answer would change with
whichever came back first. That is the bug that fabricated $2,414 of paper
profit in the graduation lab, and it is the same failure mode here.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

#: Raydium SOL/USDC. Pinned, for the reason in the module docstring.
SOL_USDC_POOL = "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2"
GECKO_POOL_URL = (
    "https://api.geckoterminal.com/api/v2/networks/solana/pools/"
    f"{SOL_USDC_POOL}"
)
#: Sixty candles: an hour of minute closes, which is what the rail's sparkline
#: draws. More would be invisible at that width.
CANDLES = 60
TTL = timedelta(seconds=45)
TIMEOUT = 6.0


@dataclass(slots=True)
class SolPrice:
    price_usd: float
    change_pct_1h: float | None
    change_pct_24h: float | None
    #: Minute closes, oldest first — the shape the sparkline expects.
    series: list[float] = field(default_factory=list)
    fetched_at: datetime | None = None
    stale: bool = False

    @property
    def age_seconds(self) -> int:
        if self.fetched_at is None:
            return 0
        return int((datetime.now(UTC) - self.fetched_at).total_seconds())


_cache: SolPrice | None = None
_lock = asyncio.Lock()


def _pct(new: float, old: float) -> float | None:
    return ((new / old - 1) * 100) if old else None


async def _fetch() -> SolPrice:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        ohlcv = await client.get(f"{GECKO_POOL_URL}/ohlcv/minute",
                                 params={"limit": CANDLES, "currency": "usd"})
        ohlcv.raise_for_status()
        rows = ((((ohlcv.json() or {}).get("data") or {}).get("attributes") or {})
                .get("ohlcv_list") or [])
        # GeckoTerminal returns newest first; a chart reads the other way.
        closes = [float(r[4]) for r in reversed(rows)
                  if isinstance(r, list) and len(r) >= 5 and r[4]]
        if not closes:
            raise ValueError("no candles")

        day = await client.get(GECKO_POOL_URL)
        change_24h = None
        if day.status_code == 200:
            attrs = (((day.json() or {}).get("data") or {}).get("attributes") or {})
            raw = (attrs.get("price_change_percentage") or {}).get("h24")
            if raw is not None:
                change_24h = float(raw)

    return SolPrice(
        price_usd=closes[-1],
        change_pct_1h=_pct(closes[-1], closes[0]),
        change_pct_24h=change_24h,
        series=closes,
        fetched_at=datetime.now(UTC),
    )


async def get_sol_price() -> SolPrice:
    """The cached price, refreshed at most every `TTL`.

    The lock is what makes "one call per window" true rather than aspirational:
    without it, every request arriving during a refresh starts its own.
    """
    global _cache
    now = datetime.now(UTC)
    if _cache is not None and _cache.fetched_at and now - _cache.fetched_at < TTL:
        return _cache
    async with _lock:
        # Re-check: a request that waited on the lock is served by whoever held it.
        if _cache is not None and _cache.fetched_at and (
                datetime.now(UTC) - _cache.fetched_at < TTL):
            return _cache
        try:
            _cache = await _fetch()
        except Exception as exc:
            logger.warning("sol_price_fetch_failed", error=repr(exc))
            if _cache is None:
                raise
            _cache.stale = True
        return _cache


def as_dict(price: SolPrice) -> dict[str, Any]:
    return {
        "price_usd": round(price.price_usd, 4),
        "change_pct_1h": (round(price.change_pct_1h, 3)
                          if price.change_pct_1h is not None else None),
        "change_pct_24h": (round(price.change_pct_24h, 3)
                           if price.change_pct_24h is not None else None),
        "series": [round(p, 4) for p in price.series],
        "age_seconds": price.age_seconds,
        "stale": price.stale,
    }
