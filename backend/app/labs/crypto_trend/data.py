"""The read interface. Everything downstream reads comes through here — the
trend engine included, which is how "reads candles from the DB via data.py
only" is held.

Every function takes the session, as every read in this repo does; the
caller owns the transaction boundary. `data_health()` returns plain JSON
(ISO strings, floats) so the API route and the CLI print it unchanged.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.labs.crypto_trend import config
from app.labs.crypto_trend.candles import INTERVAL_MS, Candle, find_gaps, from_ms, to_ms
from app.labs.crypto_trend.models import (
    CtCandle,
    CtFunding,
    CtRegime,
    CtRun,
    CtTrendState,
    CtUniverseMember,
    CtUniverseSnapshot,
)
from app.labs.crypto_trend.regime import Regime
from app.labs.crypto_trend.trend import TrendState
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
    session: AsyncSession, symbol: str, timeframe: str, limit: int | None = None,
) -> list[Candle]:
    """The newest `limit` closed candles (default: the timeframe's window),
    oldest first."""
    limit = config.candle_window(timeframe) if limit is None else limit
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


# --- Phase 2: trend state and regime -------------------------------------------

def _state_from_row(r: CtTrendState) -> TrendState:
    return TrendState(
        symbol=r.symbol, timeframe=r.timeframe, bar_close_time=r.bar_close_time,
        computed_at=r.computed_at, direction=r.direction, strength=r.strength,
        slope=float(r.slope), atr_pct=float(r.atr_pct), bars_in_state=r.bars_in_state,
        ema_fast=float(r.ema_fast), ema_slow=float(r.ema_slow),
        ema_trend=None if r.ema_trend is None else float(r.ema_trend),
        adx=float(r.adx), structure=r.structure, structure_veto=r.structure_veto,
        close=float(r.close),
    )


async def get_trend_state(
    session: AsyncSession, symbol: str | None = None, timeframe: str | None = None,
) -> list[TrendState]:
    """The latest state per (symbol, timeframe), optionally narrowed."""
    stmt = (
        select(CtTrendState)
        .distinct(CtTrendState.symbol, CtTrendState.timeframe)
        .order_by(CtTrendState.symbol, CtTrendState.timeframe,
                  CtTrendState.bar_close_time.desc())
    )
    if symbol is not None:
        stmt = stmt.where(CtTrendState.symbol == symbol)
    if timeframe is not None:
        stmt = stmt.where(CtTrendState.timeframe == timeframe)
    return [_state_from_row(r) for r in (await session.execute(stmt)).scalars()]


async def get_regime(session: AsyncSession, limit: int = 1) -> list[Regime]:
    """The newest `limit` regime rows, newest first."""
    rows = (await session.execute(
        select(CtRegime).order_by(CtRegime.bar_close_time.desc()).limit(limit)
    )).scalars()
    return [Regime(
        bar_close_time=r.bar_close_time, computed_at=r.computed_at, coins=r.coins,
        breadth_up=float(r.breadth_up), breadth_down=float(r.breadth_down),
        btc_direction=r.btc_direction, eth_direction=r.eth_direction, regime=r.regime,
    ) for r in rows]


async def get_funding_history(
    session: AsyncSession, symbols: Sequence[str],
) -> list[tuple[str, datetime, float]]:
    """Every stored funding row for `symbols`: (symbol, settlement time, rate)."""
    rows = (await session.execute(
        select(CtFunding.symbol, CtFunding.next_funding_time, CtFunding.funding_rate)
        .where(CtFunding.symbol.in_(list(symbols)))
        .order_by(CtFunding.symbol, CtFunding.next_funding_time)
    )).all()
    return [(s, t, float(r)) for s, t, r in rows]


async def get_universe_snapshot(session: AsyncSession, name: str) -> CtUniverseSnapshot | None:
    """A frozen historical universe by name, or None."""
    return (await session.execute(
        select(CtUniverseSnapshot).where(CtUniverseSnapshot.name == name)
    )).scalar_one_or_none()
