"""`health.read` must detect a spec-hash drift against a real tournament row.

The unit tests prove the incident fires once the flag is set. This proves the
flag gets set — that the comparison actually reads the stored hash rather than
always returning False, which is the way this check fails silently.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.lab import health, spec
from app.models.lab import LabTournament

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)


async def _drift_tournament(session: AsyncSession, *, spec_hash: str) -> LabTournament:
    row = LabTournament(
        spec_version=spec.SPEC_VERSION,
        spec_hash=spec_hash,
        valid_from=NOW - timedelta(days=1),
        snapshot_at=NOW - timedelta(days=1),
        status="active",
    )
    session.add(row)
    await session.flush()
    return row


async def test_a_matching_hash_is_not_a_drift(db_session: AsyncSession) -> None:
    session = db_session
    await _drift_tournament(session, spec_hash=spec.SPEC_HASH)
    await session.commit()

    reading = await health.read(session, now=NOW)

    assert reading.spec_hash_drift is False
    assert "HALTED" not in reading.detail


async def test_a_changed_spec_is_reported_as_a_halt(db_session: AsyncSession) -> None:
    """This is the state where every container is healthy and nothing trades."""
    session = db_session
    await _drift_tournament(session, spec_hash="b" * 64)
    await session.commit()

    reading = await health.read(session, now=NOW)

    assert reading.spec_hash_drift is True
    assert reading.stored_spec_hash == "b" * 64
    assert reading.running_spec_hash == spec.SPEC_HASH
    assert reading.detail.startswith("HALTED"), reading.detail
