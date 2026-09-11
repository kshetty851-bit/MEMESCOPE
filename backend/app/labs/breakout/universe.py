"""Candidate pools -> the watched universe. Refreshed every 15 minutes.

The top half of this module is pure: two source payloads normalised to one
`Candidate`, the filter chain, and the one-pool-per-token collapse. The
bottom half is the refresh that persists the result.

A token that fails the filters is marked INACTIVE, never deleted — the row
records that it was once established, and its candles stay. Passing again
clears the flag.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.labs.breakout import config
from app.labs.breakout.models import BoRun, BoUniverseMember
from app.labs.breakout.sources import DEX, GECKO, BreakoutSource

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Candidate:
    """One pool from either source, normalised."""

    mint: str
    symbol: str | None
    name: str | None
    pool_address: str
    dex: str
    pair_created_at: datetime | None
    liquidity_usd: Decimal | None
    volume_24h_usd: Decimal | None
    price_usd: Decimal | None
    fdv: Decimal | None
    source: str


@dataclass(frozen=True, slots=True)
class Selected:
    """A candidate that survived, with the token's shallower pools attached."""

    candidate: Candidate
    alt_pools: list[dict[str, Any]] = field(default_factory=list)


# --- normalisation ------------------------------------------------------------

def _decimal(value: Any) -> Decimal | None:
    """Coerce untrusted JSON to Decimal. A NaN or an infinity would poison
    every later comparison, so neither survives."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() else None


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def from_gecko_pool(
    pool: dict[str, Any], tokens: dict[str, dict[str, Any]],
) -> Candidate | None:
    """One `/pools` row -> a Candidate.

    `tokens` maps the `included` base-token ids to their attributes, so the
    symbol and name come from the same response rather than a second call.
    Only the BASE token is considered: on a `SOL / USDC` pool the interesting
    asset is the base, and a pool whose base is a stablecoin is excluded by
    mint below rather than rescued by reading the quote side.
    """
    attributes = pool.get("attributes") or {}
    relationships = pool.get("relationships") or {}
    base_id = ((relationships.get("base_token") or {}).get("data") or {}).get("id")
    dex = ((relationships.get("dex") or {}).get("data") or {}).get("id")
    address = attributes.get("address")
    if not base_id or not dex or not address:
        return None
    token = tokens.get(base_id, {})
    # Ids are `<network>_<mint>`; the token's own `address` is authoritative
    # when it came back, the id's tail otherwise.
    mint = token.get("address") or str(base_id).split("_", 1)[-1]
    volume = attributes.get("volume_usd") or {}
    return Candidate(
        mint=str(mint),
        symbol=token.get("symbol"),
        name=token.get("name"),
        pool_address=str(address),
        dex=str(dex),
        pair_created_at=_parse_iso(attributes.get("pool_created_at")),
        liquidity_usd=_decimal(attributes.get("reserve_in_usd")),
        volume_24h_usd=_decimal(volume.get("h24")),
        price_usd=_decimal(attributes.get("base_token_price_usd")),
        fdv=_decimal(attributes.get("fdv_usd")),
        source=GECKO,
    )


def gecko_candidates(body: dict[str, Any]) -> list[Candidate]:
    """A whole `/pools` or `/trending_pools` response -> Candidates."""
    tokens = {
        item["id"]: item.get("attributes") or {}
        for item in body.get("included") or ()
        if item.get("type") == "token" and item.get("id")
    }
    found = (from_gecko_pool(pool, tokens) for pool in body.get("data") or ())
    return [c for c in found if c is not None]


def from_dex_pair(pair: dict[str, Any]) -> Candidate | None:
    """One `/tokens/v1/solana/{mints}` row -> a Candidate.

    `liquidity` is ABSENT on bonding-curve pairs — the documented DexScreener
    gap — which reads as a null liquidity and is refused by the floor, as it
    should be: an unknown reserve is not a $50,000 one.
    """
    base = pair.get("baseToken") or {}
    mint, pool, dex = base.get("address"), pair.get("pairAddress"), pair.get("dexId")
    if not mint or not pool or not dex or pair.get("chainId") != config.NETWORK:
        return None
    created_ms = pair.get("pairCreatedAt")
    created = (
        datetime.fromtimestamp(created_ms / 1000, tz=UTC)
        if isinstance(created_ms, int | float) and created_ms > 0
        else None
    )
    return Candidate(
        mint=str(mint),
        symbol=base.get("symbol"),
        name=base.get("name"),
        pool_address=str(pool),
        dex=str(dex),
        pair_created_at=created,
        liquidity_usd=_decimal((pair.get("liquidity") or {}).get("usd")),
        volume_24h_usd=_decimal((pair.get("volume") or {}).get("h24")),
        price_usd=_decimal(pair.get("priceUsd")),
        fdv=_decimal(pair.get("fdv")),
        source=DEX,
    )


# --- filters ------------------------------------------------------------------

def dex_allowed(dex: str) -> bool:
    """PREFIX match, denylist first.

    Both sources suffix their venue variants — `raydium-clmm`,
    `meteora-damm-v2`. Measured on 80 live pools, 22 cleared every other
    filter and sat on an allowed venue, and 4 of those 22 were `raydium-clmm`:
    an exact-match allow-list would have dropped all four, an 18% cut for a
    spelling. The denylist is checked first so `pumpfun` can never be admitted by a
    prefix that happens to match, and `pumpswap` (the graduated AMM, a
    different venue from the curve) still is.
    """
    lowered = dex.lower()
    if any(lowered.startswith(d) for d in config.DEX_DENYLIST):
        return False
    return any(lowered.startswith(d) for d in config.DEX_ALLOWLIST)


def reject_reason(candidate: Candidate, now: datetime) -> str | None:
    """Why this pool is not watchable, or None. Order is deliberate: the
    cheapest and most decisive checks first, so a counter of reasons reads as
    a funnel."""
    if candidate.mint in config.EXCLUDED_MINTS:
        return "excluded_mint"
    if not dex_allowed(candidate.dex):
        return "dex"
    if candidate.pair_created_at is None:
        # Unknown age is not young, but it is also not PROVEN older than a
        # week, and the whole premise is an established token.
        return "age_unknown"
    if now - candidate.pair_created_at < timedelta(days=config.MIN_AGE_DAYS):
        return "age"
    if candidate.liquidity_usd is None or candidate.liquidity_usd < config.MIN_LIQUIDITY_USD:
        return "liquidity"
    if (candidate.volume_24h_usd is None
            or candidate.volume_24h_usd < config.MIN_VOLUME_24H_USD):
        return "volume"
    return None


def select_universe(
    candidates: Iterable[Candidate], now: datetime, *, size: int = config.MAX_UNIVERSE,
) -> tuple[list[Selected], Counter[str]]:
    """Filter, collapse to one pool per token, cap by 24h volume.

    The deepest pool wins the token; the rest become `alt_pools`. Only pools
    that PASSED the filters are kept as alternates — a shallow or too-young
    pool of the same token is not a fallback, it is a pool that failed.
    """
    rejected: Counter[str] = Counter()
    by_mint: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        reason = reject_reason(candidate, now)
        if reason is not None:
            rejected[reason] += 1
            continue
        by_mint.setdefault(candidate.mint, []).append(candidate)

    selected: list[Selected] = []
    for pools in by_mint.values():
        # Deepest first; a tie breaks on volume so the ordering is total and
        # a refresh does not flip the winning pool on equal reserves.
        pools.sort(key=lambda c: (c.liquidity_usd or 0, c.volume_24h_usd or 0), reverse=True)
        best, rest = pools[0], pools[1:]
        seen: set[str] = {best.pool_address}
        alternates = []
        for other in rest:
            if other.pool_address in seen:
                continue
            seen.add(other.pool_address)
            alternates.append({
                "pool_address": other.pool_address,
                "dex": other.dex,
                "liquidity_usd": float(other.liquidity_usd or 0),
                "volume_24h_usd": float(other.volume_24h_usd or 0),
            })
        selected.append(Selected(best, alternates))

    selected.sort(key=lambda s: s.candidate.volume_24h_usd or 0, reverse=True)
    if len(selected) > size:
        rejected["over_cap"] += len(selected) - size
    return selected[:size], rejected


# --- the refresh --------------------------------------------------------------

class BreakoutUniverse:
    def __init__(self, session: AsyncSession, source: BreakoutSource) -> None:
        self._session = session
        self._source = source

    async def gather(self) -> tuple[list[Candidate], bool]:
        """`(candidates, complete)` — everything both sources will give, with
        errors contained per call.

        One source failing costs that source's candidates, not the refresh:
        GeckoTerminal alone is a working universe and so is DexScreener alone.

        **`complete` is False when the sweep was cut short** — by the deadline
        or by a failing list. It matters because `refresh` marks absent tokens
        INACTIVE, and a truncated candidate list would retire members that are
        perfectly healthy and simply were not reached. A partial sweep may add
        tokens; only a complete one may remove them.

        The deadline exists because discovery now costs ~61 calls at 2.4s
        spacing, and Celery kills the task at `task_soft_time_limit`. The
        candle pass learned that the expensive way.
        """
        stop_at = time.monotonic() + config.TICK_DEADLINE_SECONDS
        complete = True
        candidates: list[Candidate] = []

        # The network-wide ranked list, once per sort. Volume and transaction
        # count order the same 200-pool window differently.
        for sort in config.UNIVERSE_SORTS:
            for page in range(1, config.UNIVERSE_PAGES + 1):
                if time.monotonic() >= stop_at:
                    logger.info("breakout_gather_deadline", at=f"sort:{sort}", page=page)
                    return candidates, False
                try:
                    candidates += gecko_candidates(
                        await self._source.gecko_pools(page, sort=sort))
                except Exception as exc:
                    logger.warning("breakout_pools_page_failed", sort=sort, page=page,
                                   error=repr(exc))
                    complete = False
                    break  # a failing page means the next one fails too

        # Each venue's own list. This is what lifts the candidate count off
        # the 200-pool ceiling the combined ranking imposes.
        for dex in config.UNIVERSE_DEXES:
            for page in range(1, config.UNIVERSE_DEX_PAGES + 1):
                if time.monotonic() >= stop_at:
                    logger.info("breakout_gather_deadline", at=f"dex:{dex}", page=page)
                    return candidates, False
                try:
                    candidates += gecko_candidates(
                        await self._source.gecko_dex_pools(dex, page))
                except Exception as exc:
                    logger.warning("breakout_dex_page_failed", dex=dex, page=page,
                                   error=repr(exc))
                    complete = False
                    break

        try:
            candidates += gecko_candidates(await self._source.gecko_trending())
        except Exception as exc:
            logger.warning("breakout_trending_failed", error=repr(exc))
            complete = False

        mints: list[str] = []
        for fetch in (self._source.dex_boosts, self._source.dex_profiles):
            try:
                mints += [str(row["tokenAddress"]) for row in await fetch()
                          if row.get("chainId") == config.NETWORK and row.get("tokenAddress")]
            except Exception as exc:
                logger.warning("breakout_dex_list_failed", call=fetch.__name__,
                               error=repr(exc))
                complete = False
        unique = list(dict.fromkeys(mints))
        for start in range(0, len(unique), 30):
            try:
                pairs = await self._source.dex_pairs(unique[start:start + 30])
            except Exception as exc:
                logger.warning("breakout_dex_pairs_failed", error=repr(exc))
                complete = False
                break
            candidates += [c for c in map(from_dex_pair, pairs) if c is not None]
        return candidates, complete

    async def refresh(self, now: datetime) -> dict[str, Any]:
        """One universe pass. Persists, marks drops inactive, records the run."""
        started, errors = now, []
        complete = True
        try:
            candidates, complete = await self.gather()
        except Exception as exc:  # BudgetExhaustedError, or a client-level failure
            logger.exception("breakout_universe_gather_failed")
            candidates, complete, errors = [], False, [f"gather: {exc!r}"]

        selected, rejected = select_universe(candidates, now)
        if not selected:
            # A bad refresh must not empty the universe. Nothing is marked
            # inactive, the previous members stay, and the next tick retries.
            errors.append("no candidate survived the filters; universe left unchanged")
            logger.warning("breakout_universe_empty", candidates=len(candidates),
                           rejected=dict(rejected))
            return await self._record(started, now, 0, 0, 0, errors)

        before = {m.mint for m in await self.active_members()}
        after = {s.candidate.mint for s in selected}
        for item in selected:
            await self._upsert(item, now)
        # **Only a COMPLETE sweep may retire a token.** A truncated candidate
        # list is missing tokens that are perfectly healthy and simply were not
        # reached; marking those inactive would drop them out of the candle
        # sweep and close their episodes as `universe_exit`. A partial sweep
        # adds; it never removes.
        unreached = before - after
        dropped: set[str] = unreached if complete else set()
        if dropped:
            await self._session.execute(
                update(BoUniverseMember)
                .where(BoUniverseMember.mint.in_(dropped), BoUniverseMember.active.is_(True))
                .values(active=False, inactive_reason="filtered_out")
            )
        elif unreached:
            logger.info("breakout_universe_partial_sweep", unreached=len(unreached))
            errors.append(
                f"partial sweep: {len(unreached)} member(s) not seen, none retired")
        added = after - before
        logger.info("breakout_universe_refreshed", size=len(selected),
                    candidates=len(candidates), complete=complete,
                    added=sorted(added), dropped=sorted(dropped),
                    rejected=dict(rejected))
        return await self._record(started, now, len(selected), len(added), len(dropped),
                                  errors, rejected=dict(rejected))

    async def _upsert(self, item: Selected, now: datetime) -> None:
        c = item.candidate
        stmt = pg_insert(BoUniverseMember).values(
            mint=c.mint, symbol=c.symbol, name=c.name, pool_address=c.pool_address,
            dex=c.dex, pair_created_at=c.pair_created_at, liquidity_usd=c.liquidity_usd,
            volume_24h_usd=c.volume_24h_usd, price_usd=c.price_usd, fdv=c.fdv,
            holders=None, alt_pools=item.alt_pools or None, source=c.source,
            first_seen=now, last_seen=now, active=True, inactive_reason=None,
        )
        await self._session.execute(stmt.on_conflict_do_update(
            constraint="uq_bo_universe_mint",
            set_={
                "symbol": stmt.excluded.symbol, "name": stmt.excluded.name,
                "pool_address": stmt.excluded.pool_address, "dex": stmt.excluded.dex,
                "pair_created_at": stmt.excluded.pair_created_at,
                "liquidity_usd": stmt.excluded.liquidity_usd,
                "volume_24h_usd": stmt.excluded.volume_24h_usd,
                "price_usd": stmt.excluded.price_usd, "fdv": stmt.excluded.fdv,
                "alt_pools": stmt.excluded.alt_pools, "source": stmt.excluded.source,
                "last_seen": now, "active": True, "inactive_reason": None,
                # Qualifying again is a fresh start: a token retired for five
                # failed fetches must not be retired again by the sixth.
                "fetch_failures": 0, "last_error": None,
                # `first_seen` is NOT overwritten: it is the first time this
                # mint was ever watched, which is what a re-admission needs to
                # stay comparable against a token that never left.
            },
        ))

    async def active_members(self) -> list[BoUniverseMember]:
        """Active members, most liquid names first — the candle queue's order."""
        return list((await self._session.execute(
            select(BoUniverseMember)
            .where(BoUniverseMember.active.is_(True))
            .order_by(BoUniverseMember.volume_24h_usd.desc().nullslast(),
                      BoUniverseMember.mint)
        )).scalars())

    async def stale(self, now: datetime) -> bool:
        latest = await self._session.scalar(
            select(func.max(BoUniverseMember.last_seen))
            .where(BoUniverseMember.active.is_(True))
        )
        return (latest is None
                or (now - latest).total_seconds() >= config.UNIVERSE_REFRESH_SECONDS)

    async def _record(self, started: datetime, now: datetime, size: int, added: int,
                      dropped: int, errors: list[str],
                      rejected: dict[str, int] | None = None) -> dict[str, Any]:
        self._session.add(BoRun(
            phase="universe", started_at=started, finished_at=datetime.now(UTC),
            universe_size=size, added=added, dropped=dropped,
            requests=dict(self._source.requests), errors=errors or None,
        ))
        return {"phase": "universe", "universe_size": size, "added": added,
                "dropped": dropped, "rejected": rejected or {},
                "requests": dict(self._source.requests), "errors": errors}
