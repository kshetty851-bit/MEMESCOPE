"""The track record page's one read: what `service.refresh` last stored."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/track-record", tags=["track-record"])


@router.get("", summary="Coins seen, graduated and traded, and the biggest multiples")
async def track_record() -> dict[str, Any]:
    from app.core.redis import init_redis
    from app.track_record import service

    out = await service.read(await init_redis())
    if out is None:
        return {"warming_up": True, "server_time": datetime.now(UTC).isoformat()}
    return {**out, "server_time": datetime.now(UTC).isoformat()}
