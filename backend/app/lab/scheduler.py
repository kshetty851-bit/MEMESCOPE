"""V6 Strategy Lab beat. Research simulation — it can never open a real or
paper position.

Wrapped so a Lab failure is contained: the task logs and returns rather than
raising into the beat, exactly as the Arena and the research collectors do.
The Lab is instrumentation, and instrumentation must never disturb what it
observes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.lab import leaderboard, spec
from app.lab.service import LabService
from app.models.lab import LabPosition, LabSnapshot, LabTournament
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)

#: Calendar boundaries that get their own immutable snapshot (protocol §12).
#: The 24-hour one is a SNAPSHOT, not an ending — nothing here stops the
#: tournament, and a test holds that to be true.
CALENDAR_SNAPSHOTS = (("24H", 24), ("48H", 48), ("72H", 72),
                      ("7D", 168), ("14D", 336), ("21D", 504),
                      ("30D", 720), ("60D", 1440), ("90D", 2160))

#: Closed-trade milestones. A strategy's record becomes worth reading at a
#: sample size, not at a date, so these fire independently of the calendar.
TRADE_MILESTONES = (25, 50, 100, 200, 500)


@celery_app.task(name="app.lab.scheduler.lab_tick")
def lab_tick() -> dict[str, Any]:
    """Judge due checkpoints, advance open positions, snapshot at boundaries."""
    return run_async(_lab_tick())


async def _lab_tick() -> dict[str, Any]:
    if not settings.FEATURE_LAB_ENABLED:
        return {"skipped": "lab_disabled"}
    now = datetime.now(UTC)
    try:
        async with SessionFactory() as session:
            service = LabService(session)
            tournament = await service.activate(
                valid_from=settings.lab_valid_from or now
            )
            decided = await service.evaluate_due(now=now)
            settled = await service.settle(now=now)
            await service.record_equity(now=now)
            snapped = await _snapshots(session, tournament, now)
            await session.commit()
        return {"decided": decided, "settled": settled, "snapshots": snapped}
    except Exception:
        logger.exception("lab_tick_failed")
        return {"failed": True}


async def _snapshots(session, tournament: LabTournament, now: datetime) -> list[str]:
    """Write any boundary snapshot that is due and not yet written.

    Idempotent by unique constraint on (tournament, label): a restart at the
    wrong moment cannot produce a second, different 24-hour leaderboard, and a
    boundary crossed during downtime is still captured on the next tick — the
    boundary instant is the one frozen at activation, never `now`.
    """
    existing = {r for r in (await session.execute(
        select(LabSnapshot.label).where(LabSnapshot.tournament_id == tournament.id)
    )).scalars()}
    written = []
    for label, hours in CALENDAR_SNAPSHOTS:
        boundary = tournament.valid_from + timedelta(hours=hours)
        if now < boundary or label in existing:
            continue
        payload = await leaderboard.build_snapshot(
            session, tournament=tournament, label=label, boundary=boundary, now=now
        )
        session.add(LabSnapshot(
            tournament_id=tournament.id, label=label, boundary_at=boundary,
            taken_at=now, elapsed_hours=hours, payload=payload,
        ))
        if label == "24H" and tournament.snapshot_taken_at is None:
            tournament.snapshot_taken_at = now
        await session.flush()
        written.append(label)
        logger.info("lab_snapshot_written", label=label,
                    closed=payload.get("total_closed_trades"))

    # Sample-size milestones: taken when the BEST-sampled strategy first
    # reaches a threshold, because that is when its record starts to mean
    # something. Independent of the calendar and of each other.
    best = int(await session.scalar(
        select(func.count()).select_from(LabPosition)
        .where(LabPosition.status == "closed")
        .group_by(LabPosition.strategy_row_id)
        .order_by(func.count().desc()).limit(1)
    ) or 0)
    for threshold in TRADE_MILESTONES:
        label = f"TRADES_{threshold}"
        if best < threshold or label in existing:
            continue
        payload = await leaderboard.build_snapshot(
            session, tournament=tournament, label=label, boundary=now, now=now
        )
        session.add(LabSnapshot(
            tournament_id=tournament.id, label=label, boundary_at=now, taken_at=now,
            elapsed_hours=(now - tournament.valid_from).total_seconds() / 3600,
            payload=payload,
        ))
        await session.flush()
        written.append(label)
        logger.info("lab_snapshot_written", label=label, best_sampled=best)
    return written
