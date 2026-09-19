"""The two free, keyless feeds: Jupiter's token lists and DexScreener's pairs.

Paced, not rate-limited: `CallBudget(1, 60/rate)` is a minimum spacing with no
burst, because both hosts punish bursts inside their per-minute allowance
(GeckoTerminal refused its 7th call 0.7s in). A 429's `Retry-After` is read as
a FLOOR on the back-off, never a ceiling — GeckoTerminal answers
`Retry-After: 0` and then refuses for half a minute.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from types import TracebackType
from typing import Any, Self

import httpx

from app.core.logging import get_logger
from app.labs.momentum import config
from app.services.market.providers.rate_budget import CallBudget

logger = get_logger(__name__)

_RETRY = frozenset({408, 425, 429})


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() else None


def _ts(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class Listed:
    """One token on one of Jupiter's lists."""

    mint: str
    symbol: str | None
    born_at: datetime | None
    liquidity: Decimal | None
    tags: frozenset[str]
    list_name: str


def parse_listed(row: dict[str, Any], list_name: str) -> Listed | None:
    mint = row.get("id")
    if not isinstance(mint, str) or not mint:
        return None
    first = _ts((row.get("firstPool") or {}).get("createdAt"))
    minted = _ts(row.get("createdAt"))
    # The first POOL is when the market began. Fall back to the mint only
    # when Jupiter has no pool date at all.
    return Listed(mint=mint, symbol=(row.get("symbol") or None),
                  born_at=first or minted, liquidity=_dec(row.get("liquidity")),
                  tags=frozenset(t for t in (row.get("tags") or []) if isinstance(t, str)),
                  list_name=list_name)


@dataclass(frozen=True, slots=True)
class PairRow:
    """One DexScreener pair, as the lab reads it."""

    pair_address: str
    base_mint: str
    quote_mint: str
    symbol: str | None
    dex_id: str | None
    price_usd: Decimal | None
    price_native: Decimal | None
    liquidity: Decimal | None
    volume_m5: Decimal | None
    volume_h1: Decimal | None
    volume_h24: Decimal | None
    buys_m5: int | None
    sells_m5: int | None
    change_m5: Decimal | None
    change_h1: Decimal | None
    change_h24: Decimal | None
    market_cap: Decimal | None
    created_at: datetime | None
    #: When THIS row was fetched; the market moment is `FEED_LAG_S` earlier.
    fetched_at: datetime | None = None


def parse_pair(row: dict[str, Any]) -> PairRow | None:
    try:
        address = row["pairAddress"]
        base = row["baseToken"]["address"]
        quote = row["quoteToken"]["address"]
    except (KeyError, TypeError):
        return None
    txns = (row.get("txns") or {}).get("m5") or {}
    volume = row.get("volume") or {}
    change = row.get("priceChange") or {}

    def count(v: Any) -> int | None:
        return int(v) if isinstance(v, (int, float)) else None

    return PairRow(
        pair_address=address, base_mint=base, quote_mint=quote,
        symbol=(row.get("baseToken") or {}).get("symbol"),
        dex_id=row.get("dexId"),
        price_usd=_dec(row.get("priceUsd")), price_native=_dec(row.get("priceNative")),
        liquidity=_dec((row.get("liquidity") or {}).get("usd")),
        volume_m5=_dec(volume.get("m5")), volume_h1=_dec(volume.get("h1")),
        volume_h24=_dec(volume.get("h24")),
        buys_m5=count(txns.get("buys")), sells_m5=count(txns.get("sells")),
        change_m5=_dec(change.get("m5")), change_h1=_dec(change.get("h1")),
        change_h24=_dec(change.get("h24")),
        market_cap=_dec(row.get("marketCap") or row.get("fdv")),
        created_at=_ts(row.get("pairCreatedAt")),
    )


def best_pair(rows: Sequence[PairRow], mint: str) -> PairRow | None:
    """The pool to watch a token on: the most traded one that is quoted in
    SOL or a dollar, holds the floor, and has the token as its BASE.

    Base, because every field of a pair describes its base token — a pair
    where our token is the QUOTE reports someone else's price. The most TRADED
    rather than the deepest, because a candle is built from trades and a deep
    pool nobody trades prints a flat line.
    """
    ok = [r for r in rows
          if r.base_mint == mint and r.quote_mint in config.QUOTE_MINTS
          and r.price_usd and r.price_usd > 0
          and (r.liquidity or 0) >= config.MIN_PAIR_LIQUIDITY_USD]
    if not ok:
        return None
    return max(ok, key=lambda r: (r.volume_h24 or 0, r.liquidity or 0))


class Feeds:
    """Jupiter lists and DexScreener pairs behind one paced client."""

    def __init__(self, *, client: httpx.AsyncClient | None = None,
                 dex_per_minute: int | None = None) -> None:
        self._client = client
        self._owns = client is None
        rate = dex_per_minute or config.DEXSCREENER_CALLS_PER_MINUTE
        self._pace = {
            "dex": CallBudget(1, 60.0 / rate),
            "jup": CallBudget(1, 60.0 / config.JUPITER_CALLS_PER_MINUTE),
        }
        self.calls = {"dex": 0, "jup": 0}
        self.failures = 0

    async def __aenter__(self) -> Self:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(config.HTTP_TIMEOUT_SECONDS),
                headers={"accept": "application/json",
                         "user-agent": config.USER_AGENT})
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None,
                        exc: BaseException | None, tb: TracebackType | None) -> None:
        if self._owns and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get(self, url: str, host: str) -> Any:
        assert self._client is not None, "Feeds used outside `async with`"
        pace = self._pace[host]
        for attempt in range(1, config.HTTP_MAX_ATTEMPTS + 1):
            while not pace.try_acquire(1):  # noqa: ASYNC110 - a pacing spin, not an event
                await asyncio.sleep(0.05)
            self.calls[host] += 1
            response = await self._client.get(url)
            if response.status_code in _RETRY or response.status_code >= 500:
                try:
                    floor = float(response.headers.get("retry-after") or 0)
                except ValueError:
                    floor = 0.0
                await asyncio.sleep(min(max(floor, 2.0 * attempt), 20.0))
                continue
            response.raise_for_status()
            return response.json()
        raise RuntimeError(f"momentum lab gave up on {url.split('?')[0]}")

    async def listed(self) -> list[Listed]:
        """Every token on every list and window. A list that fails is skipped:
        the universe keeps what it had rather than shrinking to what answered."""
        out: list[Listed] = []
        for name in config.JUPITER_LISTS:
            for window in config.JUPITER_WINDOWS:
                label = f"{name}/{window}"
                try:
                    body = await self._get(
                        f"{config.JUPITER_URL}/{name}/{window}?limit={config.JUPITER_LIMIT}",
                        "jup")
                except Exception as exc:  # one list must not sink the refresh
                    self.failures += 1
                    logger.warning("momentum_jupiter_failed", list=label, error=repr(exc))
                    continue
                for row in body or []:
                    if isinstance(row, dict) and (item := parse_listed(row, label)):
                        out.append(item)
        for tag in config.JUPITER_TAGS:
            label = f"tag/{tag}"
            try:
                body = await self._get(f"{config.JUPITER_URL}/tag?query={tag}", "jup")
            except Exception as exc:
                self.failures += 1
                logger.warning("momentum_jupiter_failed", list=label, error=repr(exc))
                continue
            for row in body or []:
                if isinstance(row, dict) and (item := parse_listed(row, label)):
                    out.append(item)
        return out

    async def token_pairs(self, mint: str) -> list[PairRow]:
        """Every pool DexScreener knows for one token."""
        try:
            body = await self._get(
                f"{config.DEXSCREENER_URL}/token-pairs/v1/solana/{mint}", "dex")
        except Exception as exc:
            self.failures += 1
            logger.warning("momentum_token_pairs_failed", mint=mint, error=repr(exc))
            return []
        return [p for row in (body or []) if isinstance(row, dict)
                and (p := parse_pair(row))]

    async def pairs(self, addresses: Sequence[str]) -> dict[str, PairRow]:
        """The given pools, BY ADDRESS, thirty to a call, a few calls at once."""
        chunks = [addresses[i:i + config.DEXSCREENER_BATCH]
                  for i in range(0, len(addresses), config.DEXSCREENER_BATCH)]

        async def one(chunk: Sequence[str]) -> list[PairRow]:
            try:
                body = await self._get(
                    f"{config.DEXSCREENER_URL}/latest/dex/pairs/solana/{','.join(chunk)}",
                    "dex")
            except Exception as exc:
                self.failures += 1
                logger.warning("momentum_pairs_failed", pairs=len(chunk), error=repr(exc))
                return []
            now = datetime.now(UTC)
            rows = (body or {}).get("pairs") or []
            return [replace(p, fetched_at=now) for row in rows
                    if isinstance(row, dict) and (p := parse_pair(row))]

        found: dict[str, PairRow] = {}
        for rows in await asyncio.gather(*(one(c) for c in chunks)):
            for row in rows:
                found[row.pair_address] = row
        return found
