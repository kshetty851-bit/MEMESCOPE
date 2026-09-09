"""Stamp every newly-listed pool we have not seen before.

The whole job is to beat the discovery window. GeckoTerminal's `new_pools`
feed reaches back about seventy minutes; a launch missed is a launch that
cannot be studied, because no endpoint will hand it back later. Prices are NOT
collected here — minute OHLCV is retroactive per pool, so the stamp is the only
perishable thing.

Idempotent by unique constraint on (network, pool_address): two passes that
overlap, or a restart mid-pass, cannot produce a second row or a second
`first_seen_at` for the same pool.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert

from app.core.logging import get_logger
from app.evmchain.gecko import GeckoTerminal, parse_pool
from app.models.basechain import EvmLaunch

logger = get_logger(__name__)


async def discover(session, *, network: str, pages: int,
                   now: datetime | None = None) -> dict[str, int]:
    """One pass. Returns what it saw and what was new."""
    now = now or datetime.now(UTC)
    counts = {"seen": 0, "unparsable": 0, "stamped": 0}

    async with GeckoTerminal() as api:
        rows = await api.new_pools(network, pages=pages)

    records: list[dict[str, Any]] = []
    for row in rows:
        counts["seen"] += 1
        parsed = parse_pool(row, network, now=now)
        if parsed is None:
            counts["unparsable"] += 1
            continue
        records.append(parsed)

    if not records:
        return counts

    # ON CONFLICT DO NOTHING, not an existence check followed by an insert:
    # two overlapping passes would both pass the check and one would raise.
    # `first_seen_at` must never be overwritten — it is the observation.
    stmt = (
        insert(EvmLaunch)
        .values(records)
        .on_conflict_do_nothing(constraint="uq_evm_launches_pool")
        .returning(EvmLaunch.id)
    )
    counts["stamped"] = len((await session.execute(stmt)).all())
    return counts
