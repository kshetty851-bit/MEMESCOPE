"""`/tracker` — read-only. No POST/PUT/PATCH/DELETE.

Mounted under `settings.API_V1_PREFIX` like every other router here, so the
brief's `/api/tracker/health` is served at `/api/v1/tracker/health`.

With the flag off every route answers `running: false` without touching the
database.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.labs.nse_breakout import config
from app.labs.nse_breakout.data import (
    get_breakouts,
    get_episodes,
    get_near,
    get_stats,
    get_stock,
    health,
)

router = APIRouter(prefix="/tracker", tags=["nse-breakout-tracker"])


@router.get("/health")
async def tracker_health(session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Universe size, candle coverage, last bhavcopy date, backfill progress,
    failures, and what is known about corporate actions."""
    return await health(session)


@router.get("/near")
async def tracker_near(limit: int = Query(200, ge=1, le=1000),
                       session: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    """Stocks currently NEAR or WATCH. NEAR first, then by score."""
    if not config.enabled():
        return []
    return await get_near(session, limit=limit)


@router.get("/breakouts")
async def tracker_breakouts(days: int = Query(30, ge=1, le=365),
                            source: str = Query("live", pattern="^(live|replay)$"),
                            session: AsyncSession = Depends(get_db),
                            ) -> list[dict[str, Any]]:
    """Episodes whose breakout confirmed in the last `days` days."""
    if not config.enabled():
        return []
    return await get_breakouts(session, days=days, source=source)


@router.get("/stock/{symbol}")
async def tracker_stock(symbol: str,
                        candles: int = Query(750, ge=1, le=3000),
                        session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Levels, score, the open episode, the episode history and the bars."""
    if not config.enabled():
        raise HTTPException(status_code=503, detail="tracker_disabled")
    payload = await get_stock(session, symbol.upper(), candles=candles)
    if payload is None:
        raise HTTPException(status_code=404, detail="unknown_symbol")
    return payload


@router.get("/episodes")
async def tracker_episodes(source: str = Query("replay", pattern="^(live|replay)$"),
                           limit: int = Query(100, ge=1, le=1000),
                           offset: int = Query(0, ge=0),
                           session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    if not config.enabled():
        return {"total": 0, "limit": limit, "offset": offset, "items": []}
    return await get_episodes(session, source=source, limit=limit, offset=offset)


@router.get("/stats")
async def tracker_stats(source: str = Query("replay", pattern="^(live|replay)$"),
                        session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """What the episodes of one source actually did, and under which rules."""
    if not config.enabled():
        return {"episodes": 0, "source": source, "running": False}
    return await get_stats(session, source=source)
