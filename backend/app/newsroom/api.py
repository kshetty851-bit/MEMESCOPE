"""The public newspaper read: one cached bundle, built every two minutes."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Response

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


@router.get("/bulletin", summary="The newsroom TV's latest spoken bulletin")
async def bulletin() -> dict[str, Any]:
    """Makes a new bulletin first when the last one is stale (see `anchor`)."""
    from app.core.config import settings
    from app.core.redis import init_redis
    from app.newsroom import anchor
    from app.newsroom.refresh import KEY

    redis = await init_redis()
    key = settings.OPENAI_API_KEY.get_secret_value()
    meta = await anchor.bulletin(redis, json.loads(await redis.get(KEY) or "{}"), key)
    if not meta:
        return {"on_air": False, "reason": "no_key" if not key else "warming_up"}
    return {"on_air": True, **meta, "audio": f"/api/v1/newsroom/bulletin/{meta['id']}.mp3"}


@router.get("/bulletin/{bid}.mp3", summary="One bulletin's audio")
async def bulletin_audio(bid: str) -> Response:
    from app.core.redis import init_redis
    from app.newsroom import anchor

    data = await anchor.audio(await init_redis(), bid)
    if data is None:
        raise HTTPException(status_code=404, detail="no such bulletin")
    return Response(data, media_type="audio/mpeg",
                    headers={"Cache-Control": "public, max-age=21600, immutable"})
