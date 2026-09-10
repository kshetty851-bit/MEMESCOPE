"""A universe frozen at a past date, for out-of-sample replays.

The live universe is today's top-20, so a replay over it rewards coins that
rallied their way in. A snapshot ranks today's top `SNAPSHOT_FETCH` (60)
coins by their market cap ON `as_of` instead — from CoinGecko's daily
`market_chart` — applies the same exclusions, keeps the top 20 that have a
Binance perp today, and stores the list in `ct_universe_snapshots`. Any
symbol without stored candles is then backfilled on both timeframes.

Two residues survive, and the README says so: the candidates are still
today's top-60 (a coin that was top-20 in March and has since fallen below
60th, or been delisted from Binance perps, is not here), and the public
CoinGecko API serves at most 365 days of history — `days=max` is a paid
plan — so `as_of` cannot be older than that.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.labs.crypto_trend import config
from app.labs.crypto_trend.candles import to_ms
from app.labs.crypto_trend.models import (
    CtCandle,
    CtUniverseMember,
    CtUniverseSnapshot,
)
from app.labs.crypto_trend.service import CryptoTrendService
from app.labs.crypto_trend.sources import MarketSource
from app.labs.crypto_trend.universe import is_excluded, map_symbol

logger = get_logger(__name__)

DAY_MS = 86_400_000


@dataclass(frozen=True, slots=True)
class SnapshotCoin:
    symbol: str
    coingecko_id: str
    ticker: str
    name: str
    market_cap_usd: float
    rank: int


def cap_at(points: Sequence[Sequence[float]], as_of_ms: int) -> float | None:
    """The last daily market cap on or before the END of `as_of`'s day."""
    cutoff = as_of_ms + DAY_MS - 1
    best: tuple[float, float] | None = None
    for ts, cap in points:
        if ts <= cutoff and cap and (best is None or ts > best[0]):
            best = (ts, cap)
    return None if best is None else best[1]


def rank_snapshot(
    markets: Sequence[Mapping[str, Any]], charts: Mapping[str, Sequence[Sequence[float]]],
    perps: set[str], *, as_of_ms: int, size: int = config.UNIVERSE_SIZE,
) -> tuple[list[SnapshotCoin], list[dict[str, str]]]:
    """Today's candidates ranked by their cap on `as_of`. Pure."""
    ranked: list[tuple[float, Mapping[str, Any], str]] = []
    skipped: list[dict[str, str]] = []
    for m in markets:
        if is_excluded(m):
            continue
        coin_id, ticker = str(m["id"]), str(m["symbol"]).upper()
        cap = cap_at(charts.get(coin_id, ()), as_of_ms)
        if cap is None:
            skipped.append({"coingecko_id": coin_id, "why": "no market cap on as_of"})
            continue
        symbol = map_symbol(coin_id, ticker)
        if symbol not in perps:
            skipped.append({"coingecko_id": coin_id, "why": f"no Binance perp {symbol}"})
            continue
        ranked.append((cap, m, symbol))
    ranked.sort(key=lambda t: (-t[0], t[2]))
    coins = [SnapshotCoin(symbol=symbol, coingecko_id=str(m["id"]),
                          ticker=str(m["symbol"]).upper(),
                          name=str(m.get("name") or m["symbol"]),
                          market_cap_usd=cap, rank=i + 1)
             for i, (cap, m, symbol) in enumerate(ranked[:size])]
    return coins, skipped


class SnapshotService:
    def __init__(self, session: AsyncSession, source: MarketSource) -> None:
        self._session = session
        self._source = source

    async def create(self, *, name: str, as_of: datetime, now: datetime) -> dict[str, Any]:
        back = (now.date() - as_of.date()).days
        if back < 1:
            raise ValueError("as_of must be in the past")
        days = back + 2  # cover the as_of day itself
        if days > config.COINGECKO_MAX_HISTORY_DAYS:
            raise ValueError(f"as_of is {days} days back; the public CoinGecko API serves "
                             f"{config.COINGECKO_MAX_HISTORY_DAYS} at most")
        markets = await self._source.coingecko_markets(per_page=config.SNAPSHOT_FETCH)
        perps = await self._source.binance_perps()
        charts: dict[str, list[list[float]]] = {}
        for m in markets:
            if is_excluded(m):
                continue
            charts[str(m["id"])] = await self._source.coingecko_market_chart(str(m["id"]),
                                                                              days=days)
        coins, skipped = rank_snapshot(markets, charts, perps, as_of_ms=to_ms(as_of))
        if not coins:
            raise RuntimeError("the ranking produced no coin; nothing stored")

        stmt = pg_insert(CtUniverseSnapshot).values(
            name=name, as_of=as_of, symbols=[asdict(c) for c in coins])
        await self._session.execute(stmt.on_conflict_do_update(
            constraint="uq_ct_universe_snapshots_name",
            set_={"as_of": stmt.excluded.as_of, "symbols": stmt.excluded.symbols}))

        data = CryptoTrendService(self._session, self._source)
        new: list[str] = []
        for c in coins:
            have = await self._session.scalar(
                select(func.count()).select_from(CtCandle)
                .where(CtCandle.symbol == c.symbol, CtCandle.timeframe == "4h"))
            if have:
                continue
            new.append(c.symbol)
            for tf in config.TIMEFRAMES:
                await data.sync_candles(c.symbol, tf, now)
        backfill = await data.backfill_to_match(new, timeframe="1h", reference="4h", now=now)
        await self._session.flush()
        logger.info("crypto_trend_snapshot", name=name, as_of=as_of.isoformat(),
                    size=len(coins), new_symbols=new, requests=self._source.requests)
        return {"name": name, "as_of": as_of.isoformat(), "size": len(coins),
                "symbols": [c.symbol for c in coins], "skipped": skipped,
                "new_symbols": new, "backfill_requests": backfill["requests"],
                "requests": self._source.requests}


# --- a universe from stored coverage (Phase 3.2) ----------------------------------

async def known_symbols(session: AsyncSession, extra: Sequence[str] = ()) -> list[str]:
    """Every symbol the lab knows: the live universe, every stored snapshot,
    and whatever `extra` names."""
    live = list((await session.execute(
        select(CtUniverseMember.binance_symbol).distinct())).scalars())
    snapshots = (await session.execute(select(CtUniverseSnapshot.symbols))).scalars()
    frozen = [entry["symbol"] for row in snapshots for entry in row]
    return sorted({*live, *frozen, *extra})


async def coverage(session: AsyncSession, timeframe: str) -> dict[str, datetime]:
    """The first stored candle per symbol on `timeframe`."""
    rows = (await session.execute(
        select(CtCandle.symbol, func.min(CtCandle.open_time))
        .where(CtCandle.timeframe == timeframe).group_by(CtCandle.symbol))).all()
    return dict(rows)


async def snapshot_from_coverage(
    session: AsyncSession, *, name: str, since: datetime, timeframe: str = "1d",
) -> dict[str, Any]:
    """Freeze a universe from what is STORED rather than from a ranking:
    every symbol whose `timeframe` history reaches back to `since`.

    This is how the Phase 3.2 daily universe is built, and its membership
    rule is coverage, not market cap — see the README's caveat.
    """
    first_seen = await coverage(session, timeframe)
    qualifying = sorted(s for s, first in first_seen.items() if first <= since)
    if not qualifying:
        raise RuntimeError(f"no symbol has {timeframe} history back to {since.date()}")
    entries = [{"symbol": s, "coingecko_id": None, "ticker": s.removesuffix("USDT"),
                "name": s, "market_cap_usd": None, "rank": i + 1,
                "first_candle": first_seen[s].isoformat()}
               for i, s in enumerate(qualifying)]
    stmt = pg_insert(CtUniverseSnapshot).values(name=name, as_of=since, symbols=entries)
    await session.execute(stmt.on_conflict_do_update(
        constraint="uq_ct_universe_snapshots_name",
        set_={"as_of": stmt.excluded.as_of, "symbols": stmt.excluded.symbols}))
    await session.flush()
    excluded = {s: first_seen[s].date().isoformat()
                for s in sorted(first_seen) if first_seen[s] > since}
    logger.info("crypto_trend_coverage_snapshot", name=name, size=len(entries),
                since=since.isoformat())
    return {"name": name, "since": since.isoformat(), "timeframe": timeframe,
            "size": len(entries),
            "symbols": {e["symbol"]: e["first_candle"][:10] for e in entries},
            "excluded_too_short": excluded}
