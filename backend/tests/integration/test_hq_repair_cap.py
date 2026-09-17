"""The repair cap counts repairs that ran, not only repairs that failed."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.hq_ops.service import MAX_REPAIR_ATTEMPTS, _attempts_so_far
from app.models.hq_ops import HqAction, HqIncident

pytestmark = pytest.mark.integration


async def test_successful_runs_count_toward_the_cap(db_session: AsyncSession) -> None:
    """`disk.run_retention` "succeeds" whenever the prune was queued, and the
    disk does not move when rows are deleted. Counting only failures re-queued
    it every tick, 29 times an hour on prod. A refused run did nothing, so it
    still does not count."""
    incident = HqIncident(
        code="HQ-TEST-0001", sequence=1, kind="incident", component="disk",
        severity="warning", status="verifying", autonomy="green",
        signature="disk:warning")
    db_session.add(incident)
    await db_session.flush()
    for outcome in ["succeeded"] * MAX_REPAIR_ATTEMPTS + ["skipped"]:
        db_session.add(HqAction(
            incident_id=incident.id, agent="patch", action="disk.run_retention",
            autonomy="green", reason="test", outcome=outcome))
    await db_session.flush()

    assert await _attempts_so_far(
        db_session, incident, "disk.run_retention") == MAX_REPAIR_ATTEMPTS
