"""The lifecycle split between DISCOVERY and TRADING ELIGIBILITY.

    DISCOVERED -> OBSERVING -> QUALIFIED | REJECTED | EXPIRED -> RADAR

V1/EQ-V1's first recommendation, V4's first build item: tokens were being
admitted to the Track Record at a median age of 17-25 *minutes*, before any
observation window existed — which is why 74-82% of the features research
needed were missing at decision time, and why the admitted population was
60-90% catastrophic. The Radar engine still judges; this module only refuses
to let a first detection become an *admission* until the token has been
observable for a minimum window.

What this deliberately is NOT: a tuned trading rule. `RADAR_MIN_OBSERVATION_
MINUTES` is an operational containment default, recorded per row so history
stays readable if it changes. The research value is the OBSERVING population
itself — densely enriched from discovery (the nursery enrichment lane already
does this), with every decision timestamped, so a future study can reconstruct
"what was knowable N minutes after discovery" for any N without leakage.

While a token is OBSERVING it is invisible to the Track Record and to both
wallets (which only see admissions). Its snapshots keep accumulating; nothing
else happens to it. The decision at the window is recorded once:

* QUALIFIED — still passes the Radar gates at/after the window; admitted.
* REJECTED  — evaluated at/after the window and no longer qualifies. The
  admission stays possible later (the Radar re-evaluates forever); a late
  admission sets `admitted_at` while the window decision stands as history.
* EXPIRED   — never re-evaluated past the window (died, unpriced, or fell out
  of every candidate set) for `RADAR_NURSERY_EXPIRE_HOURS`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.research_data import NurseryAdmission
from app.radar.models import OpportunityResult, RadarSeries

logger = get_logger(__name__)

OBSERVING = "observing"
QUALIFIED = "qualified"
REJECTED = "rejected"
EXPIRED = "expired"


def window_minutes() -> int:
    return settings.RADAR_MIN_OBSERVATION_MINUTES


def age_minutes(series: RadarSeries, *, now: datetime) -> float | None:
    """Minutes since on-chain discovery. None when discovery time is unknown —
    an unknown age is held, not admitted: refusing to guess is the point."""
    if series.discovered_at is None:
        return None
    return (now - series.discovered_at).total_seconds() / 60.0


class NurseryGate:
    """The one decision: hold a would-be first detection, or release it."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def hold(self, series: RadarSeries, result: OpportunityResult, *, now: datetime) -> bool:
        """True when the token must stay in the nursery instead of admitting.

        Only ever called for a token that qualified and has no Radar row yet.
        Upserts the OBSERVING record so the research trail starts at the first
        qualifying evaluation, not at the eventual admission.
        """
        window = window_minutes()
        if window <= 0:
            return False
        if series.token_id is None:
            return False  # cannot be admitted anyway (no discovery row)

        age = age_minutes(series, now=now)
        if age is not None and age >= window:
            return False

        stmt = (
            pg_insert(NurseryAdmission)
            .values(
                token_id=series.token_id,
                mint_address=series.mint_address,
                entered_at=now,
                status=OBSERVING,
                window_minutes=window,
                entry_score=result.score,
            )
            .on_conflict_do_nothing(index_elements=[NurseryAdmission.token_id])
        )
        await self._session.execute(stmt)
        return True

    async def record_window_decision(
        self, series: RadarSeries, *, qualified: bool, reason: str, now: datetime
    ) -> None:
        """Write the at-window verdict exactly once; later calls change nothing."""
        await self._session.execute(
            update(NurseryAdmission)
            .where(
                NurseryAdmission.token_id == series.token_id,
                NurseryAdmission.status == OBSERVING,
            )
            .values(
                status=QUALIFIED if qualified else REJECTED,
                decided_at=now,
                decision_reason=reason[:64],
            )
        )

    async def record_admission(self, series: RadarSeries, *, now: datetime) -> None:
        """Stamp the admission moment on whatever row exists, whatever it says."""
        await self._session.execute(
            update(NurseryAdmission)
            .where(
                NurseryAdmission.token_id == series.token_id,
                NurseryAdmission.admitted_at.is_(None),
            )
            .values(admitted_at=now)
        )


async def expire_stale(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Sweep OBSERVING rows that were never decided. Returns how many expired."""
    moment = now or datetime.now(UTC)
    cutoff = moment - timedelta(hours=settings.RADAR_NURSERY_EXPIRE_HOURS)
    result = await session.execute(
        update(NurseryAdmission)
        .where(
            NurseryAdmission.status == OBSERVING,
            NurseryAdmission.entered_at < cutoff,
        )
        .values(status=EXPIRED, decided_at=moment, decision_reason="never_reevaluated_past_window")
        .returning(NurseryAdmission.id)
    )
    expired = len(result.scalars().all())
    if expired:
        logger.info("nursery_expired", count=expired)
    return expired


async def observing_mints(session: AsyncSession, *, limit: int = 2000) -> list[str]:
    rows = await session.execute(
        select(NurseryAdmission.mint_address)
        .where(NurseryAdmission.status == OBSERVING)
        .order_by(NurseryAdmission.entered_at)
        .limit(limit)
    )
    return list(rows.scalars())
