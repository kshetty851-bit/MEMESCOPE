"""First-party, privacy-minimal private-alpha activity read model."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.alpha_session import AlphaSession
from app.schemas.alpha import AlphaActivityOverview, AlphaActivitySession


def status_for(last_seen_at: datetime, *, now: datetime) -> str:
    age = (now - last_seen_at).total_seconds()
    if age <= settings.ALPHA_ACTIVITY_ACTIVE_SECONDS:
        return "active"
    if age <= settings.ALPHA_ACTIVITY_IDLE_SECONDS:
        return "idle"
    return "offline"


class AlphaActivityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def unlock(self, session_id: str, *, now: datetime) -> None:
        self.session.add(
            AlphaSession(
                session_id=session_id,
                unlocked_at=now,
                last_seen_at=now,
                current_path="/",
            )
        )

    async def heartbeat(self, session_id: str, path: str, *, now: datetime) -> None:
        row = await self.session.scalar(
            select(AlphaSession).where(AlphaSession.session_id == session_id)
        )
        if row is None:
            # A cookie may predate this additive telemetry table. It still gets
            # an anonymous row; no code or browser data is ever recovered.
            row = AlphaSession(
                session_id=session_id, unlocked_at=now, last_seen_at=now, current_path=path
            )
            self.session.add(row)
        else:
            row.last_seen_at = now
            row.current_path = path
        await self.session.execute(
            delete(AlphaSession).where(
                AlphaSession.last_seen_at
                < now - timedelta(days=settings.ALPHA_ACTIVITY_RETENTION_DAYS)
            )
        )

    async def overview(self, *, now: datetime) -> AlphaActivityOverview:
        statement = select(AlphaSession).order_by(AlphaSession.last_seen_at.desc())
        rows = list((await self.session.scalars(statement)).all())
        active = sum(status_for(row.last_seen_at, now=now) == "active" for row in rows)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        seen_today = sum(row.last_seen_at >= today for row in rows)
        return AlphaActivityOverview(
            active_now=active,
            seen_today=seen_today,
            sessions=[
                AlphaActivitySession(
                    session_id=row.session_id,
                    unlocked_at=row.unlocked_at,
                    last_seen_at=row.last_seen_at,
                    current_path=row.current_path,
                    status=status_for(row.last_seen_at, now=now),
                )
                for row in rows
            ],
        )
