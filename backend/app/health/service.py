"""Derive pipeline health from persisted state.

Every figure here is a row the pipeline actually wrote. Nothing is inferred
from a process being alive, because that is precisely the signal that lied: the
scanner container reported `Up` for the whole four days it discovered nothing.

Query cost is deliberately bounded — this endpoint is polled by dashboards and
by the scanner's own container healthcheck, so it must never become the thing
that falls over. Every timestamp read is an index-backed `max()`, and the one
genuinely expensive count (scoring backlog) is an indexed anti-join measured at
~50 ms against 1.7 M snapshot rows.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.health.schemas import (
    EnrichmentHealth,
    PipelineHealth,
    RadarHealth,
    ScannerHealth,
    ScoringHealth,
    StageStatus,
)
from app.models.market import EnrichmentStatus, TokenEnrichmentState, TokenMarketSnapshot
from app.models.radar import RadarToken
from app.models.score import TokenScore
from app.models.token import DiscoveredToken

logger = get_logger(__name__)


def classify(
    minutes: float | None, *, degraded_after: int, down_after: int
) -> StageStatus:
    """Map staleness to a status.

    `None` means the stage has never written anything. That is reported as
    `down` rather than `healthy`: a stage with no output has not proven it
    works, and on a fresh deployment "down until it produces something" is the
    honest reading.
    """
    if minutes is None or minutes >= down_after:
        return "down"
    if minutes >= degraded_after:
        return "degraded"
    return "healthy"


def _minutes_since(moment: datetime | None, *, now: datetime) -> float | None:
    if moment is None:
        return None
    # Rows written a hair in the future (clock skew between containers) would
    # otherwise produce a negative age that reads as impossibly healthy.
    return max((now - moment).total_seconds(), 0.0) / 60.0


#: Worst-first, so `max()` over this ordering picks the worst status present.
_SEVERITY: dict[StageStatus, int] = {"healthy": 0, "degraded": 1, "down": 2}


def worst(statuses: list[StageStatus]) -> StageStatus:
    """Roll several stage statuses up into one.

    An empty list means every stage is disabled, which is a coherent
    deployment (an API-only replica) and reports healthy rather than down.
    """
    if not statuses:
        return "healthy"
    return max(statuses, key=lambda status: _SEVERITY[status])


@dataclass(frozen=True, slots=True)
class ScannerState:
    """What the scanner process last published about itself.

    The scanner runs in its own container, so its reconnect counter is
    unreachable from the API except through something it writes down.
    """

    connected: bool
    reconnect_attempts: int
    failure_reason: str | None

    @classmethod
    def parse(cls, raw: str | bytes | None) -> ScannerState | None:
        """Read a published state, tolerating anything malformed.

        A health endpoint that raises because a Redis value was garbage is
        worse than one that reports the state as unknown.
        """
        if not raw:
            return None
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                return None
            return cls(
                connected=bool(payload.get("connected", False)),
                reconnect_attempts=int(payload.get("reconnect_attempts", 0)),
                failure_reason=payload.get("failure_reason") or None,
            )
        except (ValueError, TypeError):
            return None


class PipelineHealthService:
    """Read-only. Opens no transaction of its own and writes nothing."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def snapshot(self, *, now: datetime | None = None) -> PipelineHealth:
        moment = now or datetime.now(UTC)

        scanner = await self.scanner(moment)
        enrichment = await self._enrichment(moment)
        scoring = await self._scoring(moment)
        radar = await self._radar(moment)

        # Only stages that are switched on can be held against the roll-up.
        # A deployment that deliberately runs no scanner is not degraded.
        enabled: list[StageStatus] = []
        if settings.FEATURE_SCANNER_ENABLED:
            enabled.append(scanner.status)
        if settings.FEATURE_ENRICHMENT_ENABLED:
            enabled.append(enrichment.status)
        if settings.FEATURE_AI_SCORING_ENABLED:
            enabled.append(scoring.status)
        if settings.FEATURE_RADAR_ENABLED:
            enabled.append(radar.status)
        overall = worst(enabled)

        logger.info(
            "pipeline_health_observed",
            overall=overall,
            scanner=scanner.status,
            enrichment=enrichment.status,
            scoring=scoring.status,
            radar=radar.status,
            scanner_minutes=scanner.minutes_since_last_token,
            enrichment_queue_depth=enrichment.queue_depth,
            scoring_pending=scoring.pending,
            radar_tracked=radar.tracked_tokens,
            scanner_failure_reason=scanner.failure_reason,
        )

        return PipelineHealth(
            scanner=scanner,
            market_enrichment=enrichment,
            scoring=scoring,
            radar=radar,
            overall=overall,
            environment=settings.ENVIRONMENT,
            version=settings.VERSION,
            observed_at=moment,
        )

    # --- Stages --------------------------------------------------------------

    async def scanner(self, now: datetime) -> ScannerHealth:
        """Public because the container healthcheck needs this stage alone.

        Running the full `snapshot()` on a 30-second probe would charge the
        database for three stages nobody asked about.
        """
        last = await self._session.scalar(select(func.max(DiscoveredToken.discovered_at)))
        minutes = _minutes_since(last, now=now)
        status = classify(
            minutes,
            degraded_after=settings.HEALTH_SCANNER_DEGRADED_MINUTES,
            down_after=settings.HEALTH_SCANNER_DOWN_MINUTES,
        )

        state = await self._scanner_state()
        if state is not None and not state.connected:
            # The scanner knows it cannot reach Helius. That is a harder signal
            # than staleness — a quiet market also produces no rows — so it
            # takes precedence, and can only ever make the verdict worse.
            reconnect_status: StageStatus = (
                "down"
                if state.reconnect_attempts >= settings.SCANNER_RECONNECT_ERROR_ATTEMPTS
                else "degraded"
            )
            status = worst([status, reconnect_status])

        return ScannerHealth(
            status=status,
            last_discovery=last,
            minutes_since_last_token=None if minutes is None else round(minutes, 1),
            reconnect_attempts=None if state is None else state.reconnect_attempts,
            failure_reason=None if state is None else state.failure_reason,
        )

    async def _scanner_state(self) -> ScannerState | None:
        """Read the scanner's published state, or `None` if unavailable.

        Redis being down must not fail the health endpoint — `/ready` is what
        reports Redis, and this endpoint still has useful things to say about
        every other stage.
        """
        try:
            raw = await get_redis().get(settings.scanner_state_key)
        except Exception as exc:
            logger.warning("scanner_state_unreadable", error=str(exc))
            return None
        return ScannerState.parse(raw)

    async def _enrichment(self, now: datetime) -> EnrichmentHealth:
        last = await self._session.scalar(select(func.max(TokenMarketSnapshot.captured_at)))
        due = await self._session.scalar(
            select(func.count())
            .select_from(TokenEnrichmentState)
            .where(
                TokenEnrichmentState.status == EnrichmentStatus.ACTIVE,
                TokenEnrichmentState.next_refresh_at <= now,
            )
        )
        parked = await self._session.scalar(
            select(func.count())
            .select_from(TokenEnrichmentState)
            .where(TokenEnrichmentState.status == EnrichmentStatus.DEAD_LETTER)
        )
        minutes = _minutes_since(last, now=now)

        return EnrichmentHealth(
            status=classify(
                minutes,
                degraded_after=settings.HEALTH_ENRICHMENT_DEGRADED_MINUTES,
                down_after=settings.HEALTH_ENRICHMENT_DOWN_MINUTES,
            ),
            last_snapshot=last,
            minutes_since_last_snapshot=None if minutes is None else round(minutes, 1),
            queue_depth=int(due or 0),
            dead_lettered=int(parked or 0),
        )

    async def _scoring(self, now: datetime) -> ScoringHealth:
        last = await self._session.scalar(select(func.max(TokenScore.evaluated_at)))
        # Tokens with observations but no score. Deliberately *not* "tokens
        # without a score" — a token whose pool is not indexed yet has nothing
        # to score and counting it would report a permanent backlog that no
        # amount of working scoring could ever clear.
        has_snapshot = (
            select(TokenMarketSnapshot.id)
            .where(TokenMarketSnapshot.token_id == DiscoveredToken.id)
            .exists()
        )
        pending = await self._session.scalar(
            select(func.count())
            .select_from(DiscoveredToken)
            .outerjoin(TokenScore, TokenScore.token_id == DiscoveredToken.id)
            .where(TokenScore.id.is_(None), has_snapshot)
        )
        minutes = _minutes_since(last, now=now)

        return ScoringHealth(
            status=classify(
                minutes,
                degraded_after=settings.HEALTH_SCORING_DEGRADED_MINUTES,
                down_after=settings.HEALTH_SCORING_DOWN_MINUTES,
            ),
            last_score=last,
            minutes_since_last_score=None if minutes is None else round(minutes, 1),
            pending=int(pending or 0),
        )

    async def _radar(self, now: datetime) -> RadarHealth:
        # `last_evaluated_at` is updated on every sweep, whereas a radar
        # snapshot is written only on material change — so a working Radar
        # watching a quiet market writes no snapshots and would read as dead.
        last = await self._session.scalar(select(func.max(RadarToken.last_evaluated_at)))
        tracked = await self._session.scalar(select(func.count()).select_from(RadarToken))
        minutes = _minutes_since(last, now=now)

        return RadarHealth(
            status=classify(
                minutes,
                degraded_after=settings.HEALTH_RADAR_DEGRADED_MINUTES,
                down_after=settings.HEALTH_RADAR_DOWN_MINUTES,
            ),
            last_cycle=last,
            minutes_since_last_cycle=None if minutes is None else round(minutes, 1),
            tracked_tokens=int(tracked or 0),
        )


async def publish_scanner_state(
    *, connected: bool, reconnect_attempts: int, failure_reason: str | None = None
) -> None:
    """Record the scanner's connection state for the health endpoint to read.

    Best-effort by design. The scanner's job is discovery; if Redis is
    unavailable it must keep trying to reconnect to Helius rather than die
    reporting that it cannot report.
    """
    payload: dict[str, Any] = {
        "connected": connected,
        "reconnect_attempts": reconnect_attempts,
        "failure_reason": failure_reason,
        "observed_at": datetime.now(UTC).isoformat(),
    }
    try:
        await get_redis().set(
            settings.scanner_state_key,
            json.dumps(payload),
            ex=settings.SCANNER_STATE_TTL_SECONDS,
        )
    except Exception as exc:
        logger.warning("scanner_state_publish_failed", error=str(exc))
