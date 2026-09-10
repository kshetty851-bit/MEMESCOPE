"""The read interface. Everything a later phase reads comes through here.

Every function takes the session, as every read in this repo does; the
caller owns the transaction boundary. `data_health()` returns plain JSON
(ISO strings, floats) so the API route and the CLI print it unchanged.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.labs.crypto_trend import config
from app.labs.crypto_trend.candles import INTERVAL_MS, Candle, find_gaps, from_ms, to_ms
from app.labs.crypto_trend.models import CtCandle, CtFunding, CtRun, CtUniverseMember
from app.labs.crypto_trend.universe import Coin


async def get_universe(session: AsyncSession) -> list[Coin]:
    """Current members, by rank."""
    rows = (await session.execute(
        select(CtUniverseMember)
        .where(CtUniverseMember.removed_at.is_(None))
        .order_by(CtUniverseMember.rank)
    )).scalars()
    return [Coin(r.coingecko_id, r.ticker, r.name, r.binance_symbol, r.rank,
                 r.market_cap_rank, r.market_cap_usd) for r in rows]


async def get_candles(
    session: AsyncSession, symbol: str, timeframe: str, limit: int = config.CANDLE_WINDOW,
) -> list[Candle]:
    """The newest `limit` closed candles, oldest first."""
    rows = (await session.execute(
        select(CtCandle)
        .where(CtCandle.symbol == symbol, CtCandle.timeframe == timeframe)
        .order_by(CtCandle.open_time.desc())
        .limit(limit)
    )).scalars()
    return [Candle(r.symbol, r.timeframe, r.open_time, r.open, r.high, r.low, r.close,
                   r.volume, r.close_time) for r in reversed(list(rows))]


async def get_funding(session: AsyncSession, symbol: str) -> float | None:
    """The most recent funding rate seen for `symbol`, or None if never fetched."""
    rate = await session.scalar(
        select(CtFunding.funding_rate)
        .where(CtFunding.symbol == symbol)
        .order_by(CtFunding.next_funding_time.desc())
        .limit(1)
    )
    return None if rate is None else float(rate)


async def data_health(session: AsyncSession, *, now: datetime | None = None) -> dict[str, Any]:
    """Last update per symbol and timeframe, gaps, and the last tick's errors."""
    if not config.enabled():
        return {"running": False}
    now = now or datetime.now(UTC)
    now_ms = to_ms(now)

    members = await get_universe(session)
    symbols = [m.binance_symbol for m in members]
    refreshed_at = await session.scalar(
        select(CtUniverseMember.refreshed_at)
        .where(CtUniverseMember.removed_at.is_(None))
        .order_by(CtUniverseMember.refreshed_at.desc()).limit(1)
    )

    times: dict[tuple[str, str], list[int]] = defaultdict(list)
    last_close: dict[tuple[str, str], int] = {}
    for symbol, timeframe, open_time, close_time in (await session.execute(
        select(CtCandle.symbol, CtCandle.timeframe, CtCandle.open_time, CtCandle.close_time)
        .where(CtCandle.symbol.in_(symbols))
    )).all():
        key = (symbol, timeframe)
        times[key].append(to_ms(open_time))
        last_close[key] = max(last_close.get(key, 0), to_ms(close_time))

    candles: dict[str, dict[str, Any]] = {s: {} for s in symbols}
    for symbol in symbols:
        for timeframe in config.TIMEFRAMES:
            key = (symbol, timeframe)
            interval = INTERVAL_MS[timeframe]
            gaps = find_gaps(times.get(key, ()), interval)
            last = last_close.get(key)
            age = None if last is None else (now_ms - last) / 1000
            candles[symbol][timeframe] = {
                "count": len(times.get(key, ())),
                "last_close_time": None if last is None else from_ms(last).isoformat(),
                "age_seconds": age,
                # Two intervals with nothing stored means the poll is not keeping up.
                "stale": age is None or age > 2 * interval / 1000,
                "gaps": len(gaps),
                "missing_candles": sum((b - a) // interval + 1 for a, b in gaps),
                "gap_ranges": [(from_ms(a).isoformat(), from_ms(b).isoformat())
                               for a, b in gaps[:5]],
            }

    funding = {
        r.symbol: {
            "rate": float(r.funding_rate),
            "mark_price": None if r.mark_price is None else float(r.mark_price),
            "next_funding_time": r.next_funding_time.isoformat(),
            "fetched_at": r.fetched_at.isoformat(),
        }
        for r in (await session.execute(
            select(CtFunding)
            .where(CtFunding.symbol.in_(symbols))
            .distinct(CtFunding.symbol)
            .order_by(CtFunding.symbol, CtFunding.next_funding_time.desc())
        )).scalars()
    }

    run = (await session.execute(
        select(CtRun).order_by(CtRun.started_at.desc()).limit(1)
    )).scalar_one_or_none()

    return {
        "running": True,
        "universe": {
            "size": len(members),
            "refreshed_at": None if refreshed_at is None else refreshed_at.isoformat(),
            "stale": refreshed_at is None
            or (now - refreshed_at).total_seconds() >= config.UNIVERSE_REFRESH_SECONDS,
            "symbols": symbols,
        },
        "candles": candles,
        "funding": funding,
        "last_run": None if run is None else {
            "started_at": run.started_at.isoformat(),
            "finished_at": run.finished_at.isoformat(),
            "age_seconds": (now - run.started_at).total_seconds(),
            "universe_refreshed": run.universe_refreshed,
            "candles_upserted": run.candles_upserted,
            "funding_upserted": run.funding_upserted,
            "requests": run.requests,
            "skipped": run.skipped or [],
            "errors": run.errors or [],
        },
    }
