"""`/labs/breakout` — read-only. No POST/PUT/PATCH/DELETE.

With the flag off every route answers `running: false` without touching the
database: "the lab is not running" and "the lab ran and found nothing" are
different facts and must not render identically.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.labs.breakout import config
from app.labs.breakout.data import (
    data_health,
    get_candles,
    get_episodes,
    get_levels,
    get_setup_stats,
    get_setups,
    get_universe,
    latest_snapshots,
)
from app.labs.breakout.models import BoEpisode

router = APIRouter(prefix="/labs/breakout", tags=["breakout-lab"])


class TokenOut(BaseModel):
    mint: str
    symbol: str | None
    name: str | None
    pool_address: str
    dex: str
    pair_created_at: datetime
    age_days: float
    liquidity_usd: float | None
    volume_24h_usd: float | None
    price_usd: float | None
    fdv: float | None
    #: Always null in Phase 1 — no free source serves it. See `models.py`.
    holders: int | None
    alt_pools: int
    source: str
    first_seen: datetime
    last_seen: datetime
    fetch_failures: int


class UniverseOut(BaseModel):
    running: bool
    count: int
    tokens: list[TokenOut]


@router.get("/health")
async def health(session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Flag state, universe size, candle coverage, budget, and the last run of
    each phase."""
    return await data_health(session)


@router.get("/universe", response_model=UniverseOut)
async def universe(session: AsyncSession = Depends(get_db)) -> UniverseOut:
    """Active tokens with their stats, most liquid names first."""
    if not config.enabled():
        return UniverseOut(running=False, count=0, tokens=[])
    members = await get_universe(session)
    now = datetime.now(UTC)
    tokens = [
        TokenOut(
            mint=m.mint, symbol=m.symbol, name=m.name, pool_address=m.pool_address,
            dex=m.dex, pair_created_at=m.pair_created_at,
            age_days=round((now - m.pair_created_at).total_seconds() / 86400, 2),
            liquidity_usd=None if m.liquidity_usd is None else float(m.liquidity_usd),
            volume_24h_usd=None if m.volume_24h_usd is None else float(m.volume_24h_usd),
            price_usd=None if m.price_usd is None else float(m.price_usd),
            fdv=None if m.fdv is None else float(m.fdv),
            holders=m.holders, alt_pools=len(m.alt_pools or ()), source=m.source,
            first_seen=m.first_seen, last_seen=m.last_seen,
            fetch_failures=m.fetch_failures,
        )
        for m in members
    ]
    return UniverseOut(running=True, count=len(tokens), tokens=tokens)


# ============================================================================
# Phase 2 — setups, levels, episodes, stats
# ============================================================================

class SetupOut(BaseModel):
    mint: str
    symbol: str | None
    name: str | None
    pool: str | None
    state: str
    score: int
    components: dict[str, float | None]
    price: float | None
    resistance: float | None
    distance_pct: float | None
    opened_at: datetime
    first_pre_breakout_at: datetime | None
    hours_open: float
    liquidity_usd: float | None
    volume_24h_usd: float | None


class ClusterOut(BaseModel):
    level: float
    touches: int
    first: str
    last: str
    broken: bool


class LevelsOut(BaseModel):
    clusters: list[ClusterOut]
    nearest_resistance: float | None
    atr: float | None


class BarOut(BaseModel):
    t: datetime
    o: float
    h: float
    low_: float = Field(alias="l")
    c: float
    v: float | None

    model_config = {"populate_by_name": True}


class EpisodeOut(BaseModel):
    id: str
    mint: str
    symbol: str | None
    opened_at: datetime
    first_pre_breakout_at: datetime | None
    closed_at: datetime | None
    close_reason: str | None
    entry_ref_price: float | None
    resistance_at_open: float | None
    max_gain_pct_from_ref: float | None
    max_loss_pct_from_ref: float | None
    pct_at_24h: float | None
    pct_at_72h: float | None
    trail25_result_pct: float | None
    outcome_gappy: bool


class EpisodePage(BaseModel):
    total: int
    items: list[EpisodeOut]


def _bar(candle: Any) -> dict[str, Any]:
    return {"t": candle.open_time, "o": float(candle.open), "h": float(candle.high),
            "l": float(candle.low), "c": float(candle.close),
            "v": None if candle.volume_usd is None else float(candle.volume_usd)}


@router.get("/setups")
async def setups(state: str | None = None,
                 session: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    """Open episodes, PRE_BREAKOUT first then by score. Empty with the flag off."""
    if not config.enabled():
        return []
    return [SetupOut(**row).model_dump() for row in await get_setups(session, state)]


@router.get("/setups/{mint}")
async def setup_detail(mint: str,
                       session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Everything the token panel draws: the universe row, the levels, the
    latest snapshot, the open episode if there is one, and both candle series."""
    if not config.enabled():
        return {"running": False}
    members = {m.mint: m for m in await get_universe(session, active_only=False)}
    member = members.get(mint)
    levels = await get_levels(session, mint)
    snapshots = await latest_snapshots(session, [mint])
    snapshot = snapshots.get(mint)
    episode = (await session.execute(
        select(BoEpisode).where(BoEpisode.mint == mint)
        .order_by(BoEpisode.opened_at.desc()).limit(1)
    )).scalar_one_or_none()

    return {
        "running": True,
        "token": None if member is None else {
            "mint": member.mint, "symbol": member.symbol, "name": member.name,
            "pool_address": member.pool_address, "dex": member.dex,
            "pair_created_at": member.pair_created_at,
            "liquidity_usd": _num(member.liquidity_usd),
            "volume_24h_usd": _num(member.volume_24h_usd),
            "price_usd": _num(member.price_usd), "fdv": _num(member.fdv),
            "active": member.active, "inactive_reason": member.inactive_reason,
        },
        "levels": None if levels is None else {
            "clusters": levels.clusters,
            "nearest_resistance": _num(levels.nearest_resistance),
            "atr": _num(levels.atr),
        },
        "latest_snapshot": None if snapshot is None else {
            "bar_close_time": snapshot.bar_close_time, "state": snapshot.state,
            "score": snapshot.score, "components": snapshot.components,
            "price": _num(snapshot.price), "resistance": _num(snapshot.resistance),
            "distance_pct": _num(snapshot.distance_pct),
            "hourly_missing": snapshot.hourly_missing,
        },
        "episode": None if episode is None else _episode(episode, None).model_dump(),
        "candles": {
            "day": [_bar(c) for c in await get_candles(session, mint, "day")],
            "hour": [_bar(c) for c in await get_candles(session, mint, "hour")],
        },
    }


@router.get("/episodes", response_model=EpisodePage)
async def episodes(limit: int = 50, offset: int = 0, closed: bool = True,
                   session: AsyncSession = Depends(get_db)) -> EpisodePage:
    """Closed episodes by default — the record a backtest reads."""
    if not config.enabled():
        return EpisodePage(total=0, items=[])
    limit = max(1, min(limit, 500))
    total, rows = await get_episodes(session, closed=closed, limit=limit, offset=offset)
    symbols = {m.mint: m.symbol for m in await get_universe(session, active_only=False)}
    return EpisodePage(total=total,
                       items=[_episode(e, symbols.get(e.mint)) for e in rows])


@router.get("/stats")
async def stats(session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Open by state, closed by reason, and outcomes by score decile."""
    if not config.enabled():
        return {"running": False}
    return await get_setup_stats(session)


def _episode(row: BoEpisode, symbol: str | None) -> EpisodeOut:
    return EpisodeOut(
        id=str(row.id), mint=row.mint, symbol=symbol, opened_at=row.opened_at,
        first_pre_breakout_at=row.first_pre_breakout_at, closed_at=row.closed_at,
        close_reason=row.close_reason, entry_ref_price=_num(row.entry_ref_price),
        resistance_at_open=_num(row.resistance_at_open),
        max_gain_pct_from_ref=_num(row.max_gain_pct_from_ref),
        max_loss_pct_from_ref=_num(row.max_loss_pct_from_ref),
        pct_at_24h=_num(row.pct_at_24h), pct_at_72h=_num(row.pct_at_72h),
        trail25_result_pct=_num(row.trail25_result_pct),
        outcome_gappy=row.outcome_gappy,
    )


def _num(value: Any) -> float | None:
    return None if value is None else float(value)
