"""Radar orchestration.

The package's second I/O seam. Loads a series, scores it with the pure engine,
and decides what — if anything — to persist.

Three rules live here rather than in the engine, because each is about *writing*
rather than *judging*:

1. **First detection is written once.** Enforced in SQL, restated here.
2. **History is written on material change**, not every cycle, for the same
   reason `token_score_history` is: a 15-minute cadence over ten thousand
   tokens would otherwise write a million near-identical rows a week and make
   the timeline unreadable.
3. **Achievements are driven by peak, never current.** A milestone reached is
   permanent.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.radar import RadarToken
from app.radar import achievements, detector, scorer
from app.radar.models import OpportunityResult, RadarSeries
from app.radar.repository import RadarRepository

logger = get_logger(__name__)

#: A score must move this far before it earns a history row.
MATERIAL_SCORE_DELTA = Decimal("2.0")

#: …or this long must have passed, so a flat token still leaves a heartbeat and
#: the timeline does not develop unexplained gaps.
HEARTBEAT_SECONDS = 6 * 60 * 60


class RadarService:
    """Evaluate tokens and maintain the Radar record."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = RadarRepository(session)

    async def evaluate_mint(self, mint_address: str, *, now: datetime | None = None) -> bool:
        """Score one token and persist whatever changed. Returns whether it is on the Radar.

        Every write is additive. A token that no longer qualifies keeps its row,
        its history and its achievements — the record is of what the platform
        detected, not of what it currently likes.
        """
        moment = now or datetime.now(UTC)

        series = await self._repository.load_series(mint_address)
        if series is None:
            return False

        result = scorer.evaluate(series, now=moment)
        if result is None:
            return False

        category = detector.classify(result)
        existing = await self._repository.get(mint_address)

        if existing is None:
            if category is None:
                # Not interesting enough to enter the record. Nothing is written:
                # the Radar tracks what it detected, and it has not detected this.
                return False
            await self._record_first_detection(series, result, category, moment)
            return True

        await self._update_existing(existing, series, result, category, moment)
        return True

    # --- Detection -----------------------------------------------------------

    async def _record_first_detection(
        self,
        series: RadarSeries,
        result: OpportunityResult,
        category: str,
        moment: datetime,
    ) -> None:
        token_id = await self._repository.token_id_for(series.mint_address)
        if token_id is None:
            # The Radar only tracks tokens the scanner discovered; a mint with
            # market data but no discovery row would break the foreign key.
            return

        latest = series.latest
        entry = await self._repository.record_detection(
            token_id=token_id,
            mint_address=series.mint_address,
            first_detected_at=moment,
            first_price=latest.price_usd if latest else None,
            first_market_cap=latest.market_cap if latest else None,
            first_liquidity=latest.liquidity_usd if latest else None,
            first_volume_24h=latest.volume_24h if latest else None,
            first_opportunity_score=result.score,
            first_confidence=result.confidence,
            detection_reason=[reason.value for reason in result.reasons],
            category=str(category),
            current_price=latest.price_usd if latest else None,
            current_market_cap=latest.market_cap if latest else None,
            current_liquidity=latest.liquidity_usd if latest else None,
            current_opportunity_score=result.score,
            current_confidence=result.confidence,
            current_category=str(category),
            current_multiple=Decimal(1),
            peak_price=latest.price_usd if latest else None,
            peak_market_cap=latest.market_cap if latest else None,
            peak_at=moment,
            peak_multiple=Decimal(1),
            model_version=result.model_version,
            last_evaluated_at=moment,
        )

        if entry is None:
            # Another worker detected it first. Its numbers stand.
            return

        await self._write_snapshot(entry.id, series, result, str(category), moment)
        logger.info(
            "radar_token_detected",
            mint=series.mint_address,
            category=str(category),
            score=str(result.score),
            confidence=str(result.confidence),
        )

    # --- Maintenance ---------------------------------------------------------

    async def _update_existing(
        self,
        entry: RadarToken,
        series: RadarSeries,
        result: OpportunityResult,
        category: str | None,
        moment: datetime,
    ) -> None:
        latest = series.latest
        price = latest.price_usd if latest else None

        current_multiple = achievements.multiple(entry.first_price, price)

        await self._repository.update_current(
            entry,
            price=price,
            market_cap=latest.market_cap if latest else None,
            liquidity=latest.liquidity_usd if latest else None,
            score=result.score,
            confidence=result.confidence,
            # A token that no longer qualifies keeps its original category as
            # its historical label; `current_category` is what moves.
            category=str(category) if category else entry.current_category,
            current_multiple=current_multiple,
            evaluated_at=moment,
        )

        await self._maybe_write_snapshot(entry, series, result, category, moment)
        await self._award_achievements(entry, moment)

    async def _maybe_write_snapshot(
        self,
        entry: RadarToken,
        series: RadarSeries,
        result: OpportunityResult,
        category: str | None,
        moment: datetime,
    ) -> None:
        previous = await self._repository.latest_snapshot(entry.id)
        if previous is not None:
            moved = abs(result.score - previous.opportunity_score) >= MATERIAL_SCORE_DELTA
            changed_category = category is not None and str(category) != previous.category
            elapsed = (moment - previous.captured_at).total_seconds()
            if not (moved or changed_category or elapsed >= HEARTBEAT_SECONDS):
                return

        await self._write_snapshot(
            entry.id,
            series,
            result,
            str(category) if category else entry.current_category,
            moment,
        )

    async def _write_snapshot(
        self,
        radar_token_id: uuid.UUID,
        series: RadarSeries,
        result: OpportunityResult,
        category: str,
        moment: datetime,
    ) -> None:
        latest = series.latest
        await self._repository.add_snapshot(
            radar_token_id=radar_token_id,
            mint_address=series.mint_address,
            captured_at=moment,
            price=latest.price_usd if latest else None,
            market_cap=latest.market_cap if latest else None,
            liquidity=latest.liquidity_usd if latest else None,
            volume_24h=latest.volume_24h if latest else None,
            opportunity_score=result.score,
            confidence=result.confidence,
            coverage=result.coverage,
            category=category,
            dimensions={
                dimension.id.value: {
                    "available": dimension.available,
                    "score": str(dimension.score) if dimension.score is not None else None,
                    "reasons": [reason.value for reason in dimension.reasons],
                }
                for dimension in result.dimensions
            },
            reasons=[reason.value for reason in result.reasons],
            model_version=result.model_version,
        )

    async def _award_achievements(self, entry: RadarToken, moment: datetime) -> None:
        peak_multiple = entry.peak_multiple
        if peak_multiple is None:
            return

        already = await self._repository.earned_multiples(entry.id)
        earned = achievements.newly_earned(peak_multiple=peak_multiple, already_earned=already)

        for tier in earned:
            elapsed = (moment - entry.first_detected_at).total_seconds()
            await self._repository.record_achievement(
                radar_token_id=entry.id,
                mint_address=entry.mint_address,
                tier=tier.label,
                multiple=tier.multiple,
                achieved_at=moment,
                price_at_achievement=entry.peak_price,
                market_cap_at_achievement=entry.peak_market_cap,
                days_to_achieve=Decimal(max(elapsed, 0)) / Decimal(86_400),
            )
            logger.info(
                "radar_achievement",
                mint=entry.mint_address,
                tier=tier.label,
            )

    # --- Sweep ---------------------------------------------------------------

    async def sweep(self, *, limit: int = 200, now: datetime | None = None) -> dict[str, int]:
        """Evaluate a batch of candidates.

        Commits once at the end rather than per token: the whole batch is one
        logical observation of the market, and a partial commit would leave the
        record describing a moment that never existed.
        """
        moment = now or datetime.now(UTC)
        mints = await self._repository.candidate_mints(limit=limit)

        evaluated = 0
        tracked = 0
        for mint in mints:
            evaluated += 1
            if await self.evaluate_mint(mint, now=moment):
                tracked += 1

        await self._session.commit()
        logger.info("radar_sweep_completed", evaluated=evaluated, tracked=tracked)
        return {"evaluated": evaluated, "tracked": tracked}
