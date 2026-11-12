"""Mood Lab page data. Read-only."""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/labs/mood", tags=["mood-lab"])
_CACHE: tuple[float, dict[str, Any]] | None = None


@router.get("", summary="Mood Lab: Shadow and Contra on 25 meme-coin futures, each beside a random control")
async def board() -> dict[str, Any]:
    from app.core.redis import init_redis
    from app.labs.mood import mood

    global _CACHE
    if _CACHE and time.monotonic() - _CACHE[0] < 60:
        return _CACHE[1]
    out = mood.board(json.loads(await (await init_redis()).get(mood.KEY) or "{}"))
    _CACHE = (time.monotonic(), out)
    return out
