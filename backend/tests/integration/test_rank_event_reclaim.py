"""An emptied frozen table must give its disk back — but only when empty.

`radar_rank_events` stopped being written on 2026-08-22 and retention drained
it from 1,267,469 rows toward zero. DELETE frees space inside the file for that
table to reuse, and no reuse is coming, so 865MB stayed held against a disk
that was at 87%.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.radar_quality import RadarRankEvent
from app.workers.retention_tasks import _reclaim_radar_rank_events

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)


async def _row(session: AsyncSession) -> None:
    session.add(
        RadarRankEvent(
            event_key=f"rank:{uuid.uuid4().hex}",
            mint_address=f"M{uuid.uuid4().hex}"[:44],
            radar_rank=1,
            rank_band="top_10",
            event_source="test",
            observed_at=NOW - timedelta(days=1),
        )
    )
    await session.flush()


async def _count(session: AsyncSession) -> int:
    return int(await session.scalar(text("SELECT count(*) FROM radar_rank_events")) or 0)


async def test_a_populated_table_is_never_truncated(db_session: AsyncSession) -> None:
    """The guard that matters. A reclaim that fired while rows existed would
    destroy the evidence retention is deliberately still holding."""
    session = db_session
    await _row(session)
    await session.commit()
    before = await _count(session)
    assert before > 0

    freed = await _reclaim_radar_rank_events()

    assert freed == 0
    assert await _count(session) == before, "rows were destroyed by the reclaim"


async def test_an_empty_but_small_table_is_left_alone(db_session: AsyncSession) -> None:
    """No rows, but nothing worth reclaiming either — so it must not report a
    reclaim on every pass forever."""
    session = db_session
    await session.execute(text("TRUNCATE TABLE radar_rank_events"))
    await session.commit()

    assert await _reclaim_radar_rank_events() == 0
