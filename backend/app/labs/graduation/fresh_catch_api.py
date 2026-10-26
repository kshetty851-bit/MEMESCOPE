"""Fresh Catch Lab's page data: the $1,000 book over every coin decided so far."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/labs/graduation/fresh-catch", tags=["graduation-lab"])
_CACHE: tuple[float, dict[str, Any]] | None = None


@router.get("", summary="Fresh Catch Lab: $10k-$30k fresh pools, 65% buys, sold at 4 minutes")
async def board() -> dict[str, Any]:
    from app.core.redis import init_redis
    from app.labs.graduation import fresh_catch

    global _CACHE
    if _CACHE and time.monotonic() - _CACHE[0] < 60:
        return _CACHE[1]
    out = fresh_catch.book(await fresh_catch.coins(await init_redis()), datetime.now(UTC))
    _CACHE = (time.monotonic(), out)
    return out
