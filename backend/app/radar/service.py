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
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.radar import RadarToken
from app.radar import achievements, detector, scorer
from app.radar.models import OpportunityResult, RadarSeries
from app.radar.quality import PendingDecision, build_pending, capture_pending
from app.radar.repository import PeakObservation, RadarRepository

logger = get_logger(__name__)

#: A score must move this far before it earns a history row.
MATERIAL_SCORE_DELTA = Decimal("2.0")

#: …or this long must have passed, so a flat token still leaves a heartbeat and
#: the timeline does not develop unexplained gaps.
HEARTBEAT_SECONDS = 6 * 60 * 60


@dataclass(frozen=True, slots=True)
class RadarRefreshOutcome:
    """The committed result of evaluating changed observations only."""

    evaluated: int
    tracked: int
    updated_mints: tuple[str, ...]
    ranking_changed: bool


class RadarService:
    """Evaluate tokens and maintain the Radar record."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = RadarRepository(session)
        # Held in memory until the *normal* Radar transaction commits.  Research
        # persistence is then a separate best-effort transaction, so no capture
        # exception can alter ranking, detection, or scanner behaviour.
        self._pending_quality: list[PendingDecision] = []

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
                self._queue_quality(series, result, category, selected=False, moment=moment)
                # Not interesting enough to enter the existing Radar record.
                return False
            entry = await self._record_first_detection(series, result, category, moment)
            # A concurrent Radar worker can win the immutable insertion race;
            # its canonical entry, not this capture, remains authoritative.
            selected = (
                entry is not None or await self._repository.get(mint_address) is not None
            )
            self._queue_quality(series, result, category, selected=selected, moment=moment)
            return True

        await self._update_existing(existing, series, result, category, moment)
        self._queue_quality(series, result, category, selected=True, moment=moment)
        return True

    def _queue_quality(
        self,
        series: RadarSeries,
        result: OpportunityResult,
        category: str | None,
        *,
        selected: bool,
        moment: datetime,
    ) -> None:
        pending = build_pending(
            series=series,
            result=result,
            category=category,
            selected=selected,
            evaluated_at=moment,
        )
        if pending is not None:
            self._pending_quality.append(pending)

    async def capture_forward_quality(self) -> None:
        """Persist queued research rows after a successful Radar commit only."""

        pending, self._pending_quality = self._pending_quality, []
        try:
            await capture_pending(pending)
        except Exception:
            # ``capture_pending`` already protects its own I/O, but retain a
            # second boundary here so an accidental future replacement cannot
            # turn research instrumentation into a Radar failure.
            logger.exception("radar_quality_capture_boundary_failed", candidates=len(pending))

    async def refresh_mints(
        self, mint_addresses: Sequence[str], *, now: datetime | None = None
    ) -> RadarRefreshOutcome:
        """Re-evaluate only mints whose market observations just committed.

        The Radar model is pure per mint over that mint's stored series, so a
        market update never requires rescoring the universe.  The before/after
        comparison uses the existing canonical top-ten query; it catches both
        membership changes and a move such as #4 to #3 without inventing a
        parallel ranking implementation.
        """
        mints = list(dict.fromkeys(mint_addresses))
        if not mints:
            return RadarRefreshOutcome(0, 0, (), False)

        moment = now or datetime.now(UTC)
        before = await self._repository.top_mints()
        tracked: list[str] = []
        for mint in mints:
            if await self.evaluate_mint(mint, now=moment):
                tracked.append(mint)
        after = await self._repository.top_mints()

        return RadarRefreshOutcome(
            evaluated=len(mints),
            tracked=len(tracked),
            updated_mints=tuple(tracked),
            ranking_changed=before != after,
        )

    # --- Detection -----------------------------------------------------------

    async def _record_first_detection(
        self,
        series: RadarSeries,
        result: OpportunityResult,
        category: str,
        moment: datetime,
    ) -> RadarToken | None:
        token_id = series.token_id or await self._repository.token_id_for(series.mint_address)
        if token_id is None:
            # The Radar only tracks tokens the scanner discovered; a mint with
            # market data but no discovery row would break the foreign key.
            return None

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
            return None

        await self._write_snapshot(entry.id, series, result, str(category), moment)
        logger.info(
            "radar_token_detected",
            mint=series.mint_address,
            category=str(category),
            score=str(result.score),
            confidence=str(result.confidence),
        )
        return entry

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

        # The highest price anywhere in the observed window, not just the one
        # standing at this instant.
        #
        # The peak used to be raised against `price` alone — the single latest
        # snapshot at sweep time. Sweeps run every 15 minutes while enrichment
        # writes snapshots as often as every 30 seconds, so any high that
        # happened *between* two sweeps was never seen, even though the snapshot
        # capturing it was already in the database. Measured on live data, 18 of
        # 37 tracked entries under-reported their peak, the worst by 4.17x.
        #
        # This reads the window the engine was already given, so it costs no
        # extra query, and it only ever raises the peak — the monotonic
        # guarantee the track record depends on is untouched.
        # Sprint 28: take the whole observation, not just its price. Writing
        # the peak's market cap from a *different* reading than its price is
        # what left 6 of 88 rows with a peak that disagreed with itself.
        priced = [o for o in series.observations if o.price_usd is not None]
        best = max(priced, key=lambda o: (o.price_usd, o.captured_at), default=None)
        window_high = best.price_usd if best is not None else None
        window_high_observation = (
            PeakObservation(
                captured_at=best.captured_at,
                price_usd=best.price_usd,  # type: ignore[arg-type]
                market_cap=best.market_cap,
                liquidity_usd=best.liquidity_usd,
                volume_24h=best.volume_24h,
            )
            if best is not None
            else None
        )

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
            volume_24h=latest.volume_24h if latest else None,
            observed_at=latest.captured_at if latest else None,
            window_high=window_high,
            window_high_observation=window_high_observation,
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
        """Refresh everything already on the Radar, then look for new entries.

        Two populations, and they do not overlap in practice:

        * **Tracked** — already detected, with `current_*` and `peak_*` values
          that only move when something re-evaluates them.
        * **Candidates** — ranked by most recent observation, which is
          overwhelmingly whatever enrichment just touched.
        * **Rotation** — a deterministic slice of the *entire* eligible
          universe, so every project is reached on a fixed cycle.

        Sweeping candidates alone looks sufficient and is not. A token drops out
        of the most-recently-observed window within minutes of being detected
        and is then never re-evaluated again, so its return freezes at the
        multiple it had on the day it was found — measured live, 0 of 28 tracked
        entries were still in the candidate window, and staleness ran to seven
        hours. The record stops describing the market and starts describing the
        moment of detection.

        Tracked entries go first and stalest-first, so a truncated run degrades
        the refresh interval evenly instead of stranding an arbitrary subset.
        Each population gets its own budget: a growing Radar cannot crowd out
        discovery, and a busy chain cannot starve the record.

        The rotation exists because the hot window is far narrower than it
        looks. Measured live, 978 mints were snapshotted inside one sweep
        interval, so a 500-token candidate list spans about **1.8 minutes** —
        and 22,400 of 23,355 eligible projects sat permanently below the cut.
        They were not evaluated slowly; they could not be evaluated at all.
        `rotating_mints` gives each of them a guaranteed turn, so the Radar
        finally assesses the universe it collects rather than the last two
        minutes of it.

        Commits once at the end rather than per token: the whole batch is one
        logical observation of the market, and a partial commit would leave the
        record describing a moment that never existed.
        """
        moment = now or datetime.now(UTC)

        tracked_mints = await self._repository.tracked_mints(limit=limit)
        candidates = await self._repository.candidate_mints(limit=limit)

        # Which slice of the universe this sweep owns. Derived from the clock
        # rather than stored, so replicas agree without coordinating and a
        # restart cannot rewind the cycle.
        bucket = (
            int(moment.timestamp()) // settings.RADAR_SWEEP_INTERVAL_SECONDS
        ) % settings.RADAR_ROTATION_BUCKETS
        rotating = await self._repository.rotating_mints(
            limit=limit,
            bucket=bucket,
            buckets=settings.RADAR_ROTATION_BUCKETS,
        )

        # Tracked first, then the hot window, then the rotation slice.
        # De-duplicated with order preserved, so a token appearing in two
        # populations is evaluated once and keeps its highest priority.
        mints = list(dict.fromkeys([*tracked_mints, *candidates, *rotating]))

        evaluated = 0
        tracked = 0
        for mint in mints:
            evaluated += 1
            if await self.evaluate_mint(mint, now=moment):
                tracked += 1

        await self._session.commit()
        # The research writer opens a fresh transaction and swallows all of its
        # own failures.  It cannot roll back the just-committed Radar result.
        await self.capture_forward_quality()
        logger.info(
            "radar_sweep_completed",
            evaluated=evaluated,
            tracked=tracked,
            refreshed_existing=len(tracked_mints),
            rotation_bucket=bucket,
            rotation_size=len(rotating),
        )
        return {"evaluated": evaluated, "tracked": tracked}
