"""`/labs/rhood` — read-only. A recorder's window, not a lab's board.

There is no strategy here to report: no arms, no book, no wallet. This says
what the recorder has seen on Robinhood Chain and how confident it is that it
is seeing the right thing, which is the only honest thing to show while the
question is still "does this signal mean what we think".

The launch/extra-pool split is computed HERE rather than written at record
time on purpose. The recorder stores what the chain said; deciding which
events count is an interpretation, and an interpretation that can be changed
without losing data is one that can be corrected.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.labs.rhood import config
from app.labs.rhood.models import RhoodLock, RhoodSample

router = APIRouter(prefix="/labs/rhood", tags=["rhood"])

#: A token with one pair and no older listing is meeting the market for the
#: first time. More than one means the factory made an EXTRA pool for a coin
#: that already trades — HMM and INJOH do this every five minutes, and counting
#: them as launches is what made the first version of this recorder useless.
LAUNCH_MAX_PAIRS = 1


@router.get("/status", summary="What the Robinhood Chain recorder has seen")
async def status(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    day = datetime.now(UTC) - timedelta(hours=24)
    hour = datetime.now(UTC) - timedelta(hours=1)

    async def count(*where: Any) -> int:
        return int(await db.scalar(select(func.count()).select_from(RhoodLock).where(*where)) or 0)

    launches = RhoodLock.pairs_seen <= LAUNCH_MAX_PAIRS
    rows = (await db.scalars(
        select(RhoodLock).order_by(RhoodLock.block_at.desc()).limit(40))).all()
    samples = int(await db.scalar(select(func.count()).select_from(RhoodSample)) or 0)
    first = await db.scalar(select(func.min(RhoodLock.block_at)))

    return {
        "enabled": config.ENABLED,
        "chain_id": config.CHAIN_ID,
        "factory": config.FACTORY,
        "watching_since": first,
        "samples": samples,
        "events_total": await count(),
        "events_24h": await count(RhoodLock.block_at >= day),
        "launches_24h": await count(RhoodLock.block_at >= day, launches),
        "launches_1h": await count(RhoodLock.block_at >= hour, launches),
        # Not indexed by DexScreener when the pool was created. Reported rather
        # than hidden: it is how fast a price becomes available, which decides
        # whether a strategy here could ever have an entry price.
        "unpriced_24h": await count(RhoodLock.block_at >= day,
                                    RhoodLock.priced.is_(False)),
        "recent": [{
            "symbol": r.symbol,
            "name": r.name,
            "token": r.token,
            "pool": r.pair_address,
            "at": r.block_at,
            "pairs_seen": r.pairs_seen,
            "priced": r.priced,
            "is_launch": (r.pairs_seen or 0) <= LAUNCH_MAX_PAIRS,
        } for r in rows],
    }
