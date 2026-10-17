"""The public newspaper read: one cached bundle, built every two minutes."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Response

router = APIRouter(prefix="/newsroom", tags=["newsroom"])


@router.get("", summary="Everything on the newspaper homepage, in one read")
async def newsroom(response: Response) -> dict[str, Any]:
    from app.core.redis import init_redis
    from app.newsroom.refresh import KEY

    raw = await (await init_redis()).get(KEY)
    response.headers["Cache-Control"] = "public, max-age=30"
    if not raw:
        return {"warming_up": True, "server_time": datetime.now(UTC).isoformat()}
    out = json.loads(raw)
    out["server_time"] = datetime.now(UTC).isoformat()
    return out
