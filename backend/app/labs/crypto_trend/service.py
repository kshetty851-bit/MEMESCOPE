"""One tick: re-rank the universe if it is a day old, fetch whatever candles
have closed since the last stored one, refresh funding, record the run.

Idempotent and safe to run late. Every write is an upsert on a unique key,
so a retried task, two concurrent ticks, or a backfill re-run collapse to
the same rows. Each symbol's fetch runs inside its own savepoint, so one
symbol failing — a 4xx from Binance, a delisted contract — costs that
symbol this tick and nothing else.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.labs.crypto_trend import config
from app.labs.crypto_trend.candles import INTERVAL_MS, Candle, from_ms, parse_klines, to_ms
from app.labs.crypto_trend.models import CtCandle, CtFunding, CtRun, CtUniverseMember
from app.labs.crypto_trend.sources import MarketSource
from app.labs.crypto_trend.universe import select_universe

logger = get_logger(__name__)


class CryptoTrendService:
    def __init__(self, session: AsyncSession, source: MarketSource) -> None:
        self._session = session
        self._source = source

    # --- the tick -----------------------------------------------------------

    async def tick(self, *, now: datetime) -> dict[str, Any]:
        errors: list[str] = []
        skipped: list[dict[str, str]] = []
        universe_refreshed = False
        candles_n = funding_n = 0

        try:
            if await self.universe_stale(now):
                async with self._session.begin_nested():
                    skipped = await self.refresh_universe(now)
                universe_refreshed = True
        except Exception as exc:
            logger.exception("crypto_trend_universe_refresh_failed")
            errors.append(f"universe: {exc!r}")

        members = await self.active_members()
        for member in members:
            for timeframe in config.TIMEFRAMES:
                try:
                    async with self._session.begin_nested():
                        candles_n += await self.sync_candles(
                            member.binance_symbol, timeframe, now)
                except Exception as exc:
                    logger.warning("crypto_trend_symbol_failed", symbol=member.binance_symbol,
                                   timeframe=timeframe, error=repr(exc))
                    errors.append(f"{member.binance_symbol} {timeframe}: {exc!r}")

        if members:
            try:
                async with self._session.begin_nested():
                    funding_n = await self.sync_funding(
                        {m.binance_symbol for m in members}, now)
            except Exception as exc:
                logger.exception("crypto_trend_funding_failed")
                errors.append(f"funding: {exc!r}")

        pruned = await self.prune_candles()
        self._session.add(CtRun(
            started_at=now, finished_at=datetime.now(UTC),
            universe_refreshed=universe_refreshed, candles_upserted=candles_n,
            funding_upserted=funding_n, requests=self._source.requests,
            skipped=skipped or None, errors=errors or None,
        ))
        await self._session.flush()  # the new row must exist before prune counts
        await self.prune_runs()
        return {
            "universe_refreshed": universe_refreshed, "universe_size": len(members),
            "candles_upserted": candles_n, "candles_pruned": pruned,
            "funding_upserted": funding_n, "requests": self._source.requests,
            "skipped": skipped, "errors": errors,
        }

    # --- universe -----------------------------------------------------------

    async def active_members(self) -> list[CtUniverseMember]:
        return list((await self._session.execute(
            select(CtUniverseMember)
            .where(CtUniverseMember.removed_at.is_(None))
            .order_by(CtUniverseMember.rank)
        )).scalars())

    async def universe_stale(self, now: datetime) -> bool:
        latest = await self._session.scalar(
            select(func.max(CtUniverseMember.refreshed_at))
            .where(CtUniverseMember.removed_at.is_(None))
        )
        return (latest is None
                or (now - latest).total_seconds() >= config.UNIVERSE_REFRESH_SECONDS)

    async def refresh_universe(self, now: datetime) -> list[dict[str, str]]:
        """Re-rank. Returns the coins skipped for having no Binance perp."""
        markets = await self._source.coingecko_markets()
        perps = await self._source.binance_perps()
        chosen, skipped = select_universe(markets, perps)
        if not chosen:
            # A bad response must not empty the universe; keep the last good one.
            raise RuntimeError("crypto_trend: ranking produced no tradeable coin")

        before = {m.coingecko_id for m in await self.active_members()}
        after = {c.coingecko_id for c in chosen}
        for coin in chosen:
            stmt = pg_insert(CtUniverseMember).values(
                coingecko_id=coin.coingecko_id, ticker=coin.ticker, name=coin.name,
                binance_symbol=coin.binance_symbol, rank=coin.rank,
                market_cap_rank=coin.market_cap_rank, market_cap_usd=coin.market_cap_usd,
                added_at=now, refreshed_at=now, removed_at=None,
            )
            await self._session.execute(stmt.on_conflict_do_update(
                constraint="uq_ct_universe_coingecko_id",
                set_={
                    "ticker": stmt.excluded.ticker, "name": stmt.excluded.name,
                    "binance_symbol": stmt.excluded.binance_symbol,
                    "rank": stmt.excluded.rank,
                    "market_cap_rank": stmt.excluded.market_cap_rank,
                    "market_cap_usd": stmt.excluded.market_cap_usd,
                    "refreshed_at": now, "removed_at": None,
                    # A coin coming back after an absence starts a new membership.
                    "added_at": case((CtUniverseMember.removed_at.is_not(None), now),
                                     else_=CtUniverseMember.added_at),
                },
            ))
        removed = before - after
        if removed:
            await self._session.execute(
                update(CtUniverseMember)
                .where(CtUniverseMember.coingecko_id.in_(removed),
                       CtUniverseMember.removed_at.is_(None))
                .values(removed_at=now)
            )
        logger.info("crypto_trend_universe_refreshed", size=len(chosen),
                    added=sorted(after - before), removed=sorted(removed),
                    skipped=[s["tried"] for s in skipped])
        return skipped

    # --- candles ------------------------------------------------------------

    async def sync_candles(self, symbol: str, timeframe: str, now: datetime) -> int:
        """Fetch only what is missing since the last stored close. Sends no
        request at all when the next candle cannot have closed yet."""
        interval = INTERVAL_MS[timeframe]
        now_ms = to_ms(now)
        last_close = await self._session.scalar(
            select(func.max(CtCandle.close_time))
            .where(CtCandle.symbol == symbol, CtCandle.timeframe == timeframe)
        )
        start_ms: int | None = None
        if last_close is not None:
            last_close_ms = to_ms(last_close)
            if last_close_ms + interval >= now_ms:
                return 0
            # Binance's close_time is open_time + interval - 1ms, so the next
            # open is exactly one millisecond after the last close.
            start_ms = last_close_ms + 1
        rows = await self._source.klines(symbol, timeframe, start_ms=start_ms,
                                         limit=config.CANDLE_WINDOW)
        return await self.upsert_candles(parse_klines(symbol, timeframe, rows, now_ms=now_ms))

    async def upsert_candles(self, candles: list[Candle]) -> int:
        if not candles:
            return 0
        stmt = pg_insert(CtCandle).values([{
            "symbol": c.symbol, "timeframe": c.timeframe, "open_time": c.open_time,
            "open": c.open, "high": c.high, "low": c.low, "close": c.close,
            "volume": c.volume, "close_time": c.close_time,
        } for c in candles])
        await self._session.execute(stmt.on_conflict_do_update(
            constraint="uq_ct_candles_symbol_timeframe_open_time",
            set_={k: getattr(stmt.excluded, k)
                  for k in ("open", "high", "low", "close", "volume", "close_time")},
        ))
        return len(candles)

    async def prune_candles(self) -> int:
        """Keep the newest `CANDLE_WINDOW` per symbol and timeframe."""
        ranked = select(
            CtCandle.id,
            func.row_number().over(
                partition_by=(CtCandle.symbol, CtCandle.timeframe),
                order_by=CtCandle.open_time.desc(),
            ).label("rn"),
        ).subquery()
        stale = select(ranked.c.id).where(ranked.c.rn > config.CANDLE_WINDOW)
        result = await self._session.execute(delete(CtCandle).where(CtCandle.id.in_(stale)))
        return result.rowcount or 0

    # --- funding ------------------------------------------------------------

    async def sync_funding(self, symbols: set[str], now: datetime) -> int:
        rows = [r for r in await self._source.premium_index() if r.get("symbol") in symbols]
        return await self.upsert_funding(rows, now)

    async def upsert_funding(self, rows: list[dict[str, Any]], now: datetime) -> int:
        values = [{
            "symbol": r["symbol"],
            "funding_rate": Decimal(str(r.get("lastFundingRate") or "0")),
            "mark_price": Decimal(str(r["markPrice"])) if r.get("markPrice") else None,
            "next_funding_time": from_ms(int(r["nextFundingTime"])),
            "fetched_at": now,
        } for r in rows if r.get("nextFundingTime")]
        if not values:
            return 0
        stmt = pg_insert(CtFunding).values(values)
        await self._session.execute(stmt.on_conflict_do_update(
            constraint="uq_ct_funding_symbol_next_funding_time",
            set_={"funding_rate": stmt.excluded.funding_rate,
                  "mark_price": stmt.excluded.mark_price,
                  "fetched_at": stmt.excluded.fetched_at},
        ))
        return len(values)

    # --- housekeeping -------------------------------------------------------

    async def prune_runs(self) -> None:
        keep = select(CtRun.id).order_by(CtRun.started_at.desc()).limit(config.RUN_HISTORY)
        await self._session.execute(delete(CtRun).where(CtRun.id.not_in(keep)))
