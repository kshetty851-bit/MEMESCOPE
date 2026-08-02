"""Pump.fun Radar candidate admission.

This is intentionally a read-only stage over the launch scanner and market
enrichment stores. It never invokes the Opportunity Radar's scoring, technical
or community modules. Future stages attach their own signals to
``RadarCandidate.signals`` rather than replacing this stable admission model.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.radar.models import RadarCandidate
from app.radar.repository import RadarRepository

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PumpfunRadarPolicy:
    """Configuration snapshot for a single candidate scan."""

    program_id: str
    min_age_days: int
    max_age_days: int
    min_market_cap: Decimal
    min_liquidity: Decimal
    batch_limit: int

    @classmethod
    def from_settings(cls) -> PumpfunRadarPolicy:
        return cls(
            program_id=settings.PUMPFUN_PROGRAM_ID,
            min_age_days=settings.PUMPFUN_RADAR_MIN_AGE_DAYS,
            max_age_days=settings.PUMPFUN_RADAR_MAX_AGE_DAYS,
            min_market_cap=Decimal(str(settings.PUMPFUN_RADAR_MIN_MARKET_CAP)),
            min_liquidity=Decimal(str(settings.PUMPFUN_RADAR_MIN_LIQUIDITY)),
            batch_limit=settings.PUMPFUN_RADAR_BATCH_LIMIT,
        )


class PumpfunRadarScanner:
    """Select reusable Pump.fun candidates from persisted pipeline output.

    Discovery and market calls remain owned by their existing workers. Reusing
    their persisted output means batching, retries, provider rate limits and
    circuit breaking remain centralised rather than being reimplemented here.
    """

    def __init__(
        self, session: AsyncSession, *, policy: PumpfunRadarPolicy | None = None
    ) -> None:
        self._repository = RadarRepository(session)
        self._policy = policy or PumpfunRadarPolicy.from_settings()

    async def candidates(
        self, *, limit: int | None = None, offset: int = 0, now: datetime | None = None
    ) -> list[RadarCandidate]:
        return await self._repository.pumpfun_candidates(
            program_id=self._policy.program_id,
            min_age_days=self._policy.min_age_days,
            max_age_days=self._policy.max_age_days,
            min_market_cap=self._policy.min_market_cap,
            min_liquidity=self._policy.min_liquidity,
            now=now or datetime.now(UTC),
            limit=limit or self._policy.batch_limit,
            offset=offset,
        )

    async def count(self, *, now: datetime | None = None) -> int:
        return await self._repository.count_pumpfun_candidates(
            program_id=self._policy.program_id,
            min_age_days=self._policy.min_age_days,
            max_age_days=self._policy.max_age_days,
            min_market_cap=self._policy.min_market_cap,
            min_liquidity=self._policy.min_liquidity,
            now=now or datetime.now(UTC),
        )

    async def scan(
        self, *, limit: int | None = None, now: datetime | None = None
    ) -> dict[str, int]:
        """Run one bounded, read-only admission pass and report progress."""
        candidates = await self.candidates(limit=limit, now=now)
        logger.info(
            "pumpfun_radar_scan_completed",
            eligible=len(candidates),
            batch_limit=limit or self._policy.batch_limit,
            min_age_days=self._policy.min_age_days,
            max_age_days=self._policy.max_age_days,
        )
        return {"eligible": len(candidates)}
