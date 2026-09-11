"""`/tracker` — read-only. No POST/PUT/PATCH/DELETE.

Mounted under `settings.API_V1_PREFIX` like every other router here, so the
brief's `/api/tracker/health` is served at `/api/v1/tracker/health`.

With the flag off every route answers `running: false` without touching the
database.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.labs.nse_breakout.data import health

router = APIRouter(prefix="/tracker", tags=["nse-breakout-tracker"])


@router.get("/health")
async def tracker_health(session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Universe size, candle coverage, last bhavcopy date, backfill progress,
    failures, and what is known about corporate actions."""
    return await health(session)
