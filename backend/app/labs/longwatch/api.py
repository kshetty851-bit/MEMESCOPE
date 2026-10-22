"""Long-watch Lab's one read: the collector's state and both books."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter

from app.api.deps import DbSession

router = APIRouter(prefix="/labs/longwatch", tags=["longwatch-lab"])


@router.get("/board", summary="Long-watch collector, Runner and Second Wind books")
async def board(session: DbSession) -> dict[str, Any]:
    from app.labs.longwatch import service

    return await service.board(session, datetime.now(UTC))
