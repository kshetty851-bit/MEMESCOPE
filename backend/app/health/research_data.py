"""RESEARCH DATA HEALTHY / DEGRADED — said now, not discovered in week three.

One read-only service computing whether the data the next research round
depends on is actually being collected: observation cadence against the
first-hour SLA, ingest-flag rate, collector coverage, queue lag, and the
population counters. Every check carries its measured value beside its
threshold so "DEGRADED" always says why.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.market import LANE_NURSERY, TokenEnrichmentState
from app.models.radar import RadarToken
from app.models.research_data import (
    HolderSnapshot,
    NurseryAdmission,
    ResearchQuote,
    WalletFlowSnapshot,
)

HEALTHY = "RESEARCH_DATA_HEALTHY"
DEGRADED = "RESEARCH_DATA_DEGRADED"


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    ok: bool
    value: float | None
    threshold: str
    detail: str


class ResearchDataHealthService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def snapshot(self, *, now: datetime | None = None) -> dict[str, Any]:
        moment = now or datetime.now(UTC)
        checks: list[Check] = []

        cadence = await self._first_hour_cadence(moment)
        checks.append(Check(
            name="first_hour_observation_cadence",
            ok=(cadence is not None and cadence >= settings.RESEARCH_SLA_FIRST_HOUR_MIN_OBS),
            value=cadence,
            threshold=f">= {settings.RESEARCH_SLA_FIRST_HOUR_MIN_OBS} obs (median, matured cohort)",
            detail="median observations in the first hour, admissions+nursery matured in the last 6h",
        ))

        suspect_rate = await self._suspect_rate(moment)
        checks.append(Check(
            name="ingest_suspect_rate",
            ok=(suspect_rate is None or suspect_rate <= 0.02),
            value=suspect_rate,
            threshold="<= 2% of snapshots flagged (6h)",
            detail="flagged prints are stored and excluded; a spike means the provider is misbehaving",
        ))

        nursery_lag = await self._nursery_queue_lag(moment)
        checks.append(Check(
            name="nursery_queue_lag_seconds",
            ok=(nursery_lag is None or nursery_lag <= 300),
            value=nursery_lag,
            threshold="oldest due nursery refresh <= 300s late",
            detail="how far behind the fast lane is on its own promises",
        ))

        flow = await self._flow_coverage(moment)
        checks.append(Check(
            name="wallet_flow_coverage",
            ok=(not settings.FEATURE_WALLET_FLOW_ENABLED) or flow > 0,
            value=float(flow),
            threshold="> 0 rows/hour while the feature is on",
            detail="wallet-flow snapshots written in the last hour",
        ))

        holders = await self._holder_coverage(moment)
        checks.append(Check(
            name="holder_snapshot_coverage",
            ok=(not settings.FEATURE_RESEARCH_COLLECTORS_ENABLED) or holders is None or holders >= 0.5,
            value=holders,
            threshold=">= 50% of last-6h nursery entrants snapshotted",
            detail="share of nursery entrants with a holder snapshot",
        ))

        quotes = await self._quote_coverage(moment)
        checks.append(Check(
            name="research_quote_coverage",
            ok=(not settings.FEATURE_RESEARCH_COLLECTORS_ENABLED) or quotes > 0,
            value=float(quotes),
            threshold="> 0 quotes/6h while the feature is on",
            detail="router-quote samples stored in the last 6h",
        ))

        admissions_1h = await self._session.scalar(
            select(func.count()).select_from(RadarToken).where(
                RadarToken.first_detected_at >= moment - timedelta(hours=1)
            )
        )
        nursery_observing = await self._session.scalar(
            select(func.count()).select_from(NurseryAdmission).where(
                NurseryAdmission.status == "observing"
            )
        )

        verdict = HEALTHY if all(c.ok for c in checks) else DEGRADED
        return {
            "verdict": verdict,
            "observed_at": moment,
            "checks": [asdict(c) for c in checks],
            "population": {
                "admissions_1h": int(admissions_1h or 0),
                "nursery_observing": int(nursery_observing or 0),
            },
        }

    async def _first_hour_cadence(self, now: datetime) -> float | None:
        """Median first-hour observation count over the matured recent cohort.

        Matured = first hour fully elapsed, so the count is a completed fact.
        """
        value = await self._session.scalar(text(
            """
            WITH cohort AS (
                SELECT r.token_id, r.first_detected_at
                FROM radar_tokens r
                WHERE r.first_detected_at >= :since
                  AND r.first_detected_at <= :matured
                UNION
                SELECT n.token_id, n.entered_at
                FROM nursery_admissions n
                WHERE n.entered_at >= :since
                  AND n.entered_at <= :matured
            )
            SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY obs)
            FROM (
                SELECT c.token_id,
                       (SELECT count(*) FROM token_market_snapshots s
                        WHERE s.token_id = c.token_id
                          AND s.captured_at >= c.first_detected_at
                          AND s.captured_at < c.first_detected_at + interval '1 hour'
                       ) AS obs
                FROM cohort c
            ) counted
            """
        ).bindparams(since=now - timedelta(hours=6), matured=now - timedelta(hours=1)))
        return float(value) if value is not None else None

    async def _suspect_rate(self, now: datetime) -> float | None:
        row = (await self._session.execute(text(
            """
            SELECT count(*) FILTER (WHERE suspect), count(*)
            FROM token_market_snapshots WHERE captured_at >= :since
            """
        ).bindparams(since=now - timedelta(hours=6)))).one()
        flagged, total = row
        return (flagged / total) if total else None

    async def _nursery_queue_lag(self, now: datetime) -> float | None:
        oldest = await self._session.scalar(
            select(func.min(TokenEnrichmentState.next_refresh_at)).where(
                TokenEnrichmentState.priority == LANE_NURSERY,
                TokenEnrichmentState.next_refresh_at <= now,
            )
        )
        if oldest is None:
            return None
        return (now - oldest).total_seconds()

    async def _flow_coverage(self, now: datetime) -> int:
        return int(
            await self._session.scalar(
                select(func.count()).select_from(WalletFlowSnapshot).where(
                    WalletFlowSnapshot.captured_at >= now - timedelta(hours=1)
                )
            )
            or 0
        )

    async def _holder_coverage(self, now: datetime) -> float | None:
        row = (await self._session.execute(text(
            """
            SELECT
              count(*) FILTER (WHERE EXISTS (
                SELECT 1 FROM holder_snapshots h
                WHERE h.mint_address = n.mint_address AND h.failure_reason IS NULL
              )),
              count(*)
            FROM nursery_admissions n WHERE n.entered_at >= :since
            """
        ).bindparams(since=now - timedelta(hours=6)))).one()
        have, total = row
        return (have / total) if total else None

    async def _quote_coverage(self, now: datetime) -> int:
        return int(
            await self._session.scalar(
                select(func.count()).select_from(ResearchQuote).where(
                    ResearchQuote.requested_at >= now - timedelta(hours=6)
                )
            )
            or 0
        )
