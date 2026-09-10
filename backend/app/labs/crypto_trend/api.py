"""`/labs/crypto-trend` — read-only. One route, no POST/PUT/PATCH/DELETE.

With the flag off it answers `{"running": false}` without touching the
database: "the lab is not running" and "the lab ran and found nothing" are
different facts and must not render identically.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.labs.crypto_trend.data import data_health

router = APIRouter(prefix="/labs/crypto-trend", tags=["crypto-trend-lab"])


@router.get("/health")
async def health(session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """`data_health()`: last update per symbol and timeframe, gaps, errors."""
    return await data_health(session)
