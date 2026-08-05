"""Market Enrichment Worker.

Runs as its own process, fully independent of the scanner. Two inputs:

  * The Redis discovery channel — a newly discovered token is enrolled in the
    schedule the moment the scanner publishes it, so enrichment starts within
    milliseconds without the scanner ever waiting on this worker.
  * The database work queue — tokens whose `next_refresh_at` has come due.

Nothing here can block discovery. The scanner publishes fire-and-forget to
Redis; if this worker is stopped, discoveries keep landing in the database and a
backfill sweep enrols them when it starts again.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings
from app.core.events import publish_score_events
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.db.session import SessionFactory
from app.opportunities.engine import OpportunityEngine
from app.services.curve.collector import BondingCurveCollector
from app.services.market.providers.base import MarketDataProvider
from app.services.market.providers.registry import get_provider
from app.services.market.scheduler import RefreshScheduler
from app.services.market.service import MarketEnrichmentService
from app.services.scoring.service import TokenScoringService

logger = get_logger(__name__)


@dataclass
class WorkerStats:
    cycles: int = 0
    tokens_registered: int = 0
    #: Discovery messages consumed, and those that failed on their own. A
    #: failed message is now a counter rather than a dropped subscription, so
    #: it needs somewhere to be counted.
    discovery_messages: int = 0
    discovery_messages_failed: int = 0
    #: Times the subscription itself had to be re-established. Should stay near
    #: zero; a rising value means a genuine Redis or connection problem rather
    #: than a bad payload.
    listener_reconnects: int = 0
    tokens_refreshed: int = 0
    snapshots_written: int = 0
    without_market: int = 0
    failures: int = 0
    #: Tokens the provider was never asked about because it was unavailable.
    #: Kept apart from `failures` so an outage cannot be read as tokens
    #: going bad — the conflation that dead-lettered the priority lane on
    #: 2026-08-05.
    deferred: int = 0
    dead_lettered: int = 0
    degraded_cycles: int = 0
    # Scoring runs in its own transaction after enrichment commits, so its
    # counters are tracked separately - a scoring failure says nothing about
    # whether the snapshots landed.
    tokens_scored: int = 0
    score_history_written: int = 0
    score_events_published: int = 0
    scoring_failures: int = 0
    # Opportunity detection runs in its own transaction after scoring, so its
    # counters are separate too: a detection failure says nothing about whether
    # the snapshots or the scores landed.
    opportunities_opened: int = 0
    opportunity_signals: int = 0
    opportunity_events: int = 0
    opportunity_failures: int = 0
    # Curve collection reads a different source in its own transaction, so its
    # counters are separate too: a Helius outage says nothing about whether the
    # market snapshots landed.
    curve_reads: int = 0
    curve_snapshots: int = 0
    curve_unparsable: int = 0
    curve_failures: int = 0
    started_at: datetime | None = field(default=None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "cycles": self.cycles,
            "tokens_registered": self.tokens_registered,
            "discovery_messages": self.discovery_messages,
            "discovery_messages_failed": self.discovery_messages_failed,
            "listener_reconnects": self.listener_reconnects,
            "tokens_refreshed": self.tokens_refreshed,
            "snapshots_written": self.snapshots_written,
            "without_market": self.without_market,
            "failures": self.failures,
            "deferred": self.deferred,
            "dead_lettered": self.dead_lettered,
            "degraded_cycles": self.degraded_cycles,
            "tokens_scored": self.tokens_scored,
            "score_history_written": self.score_history_written,
            "score_events_published": self.score_events_published,
            "scoring_failures": self.scoring_failures,
            "opportunities_opened": self.opportunities_opened,
            "opportunity_signals": self.opportunity_signals,
            "opportunity_events": self.opportunity_events,
            "opportunity_failures": self.opportunity_failures,
            "curve_reads": self.curve_reads,
            "curve_snapshots": self.curve_snapshots,
            "curve_unparsable": self.curve_unparsable,
            "curve_failures": self.curve_failures,
            "started_at": self.started_at.isoformat() if self.started_at else None,
        }


class MarketEnrichmentWorker:
    def __init__(
        self,
        *,
        provider: MarketDataProvider | None = None,
        scheduler: RefreshScheduler | None = None,
        poll_interval: float | None = None,
        batch_limit: int | None = None,
        backfill_interval: float | None = None,
    ) -> None:
        self._provider = provider or get_provider()
        self._scheduler = scheduler or RefreshScheduler()
        self._poll_interval = poll_interval or settings.ENRICHMENT_POLL_INTERVAL_SECONDS
        self._batch_limit = batch_limit or settings.ENRICHMENT_BATCH_LIMIT
        self._backfill_interval = (
            backfill_interval
            if backfill_interval is not None
            else settings.ENRICHMENT_BACKFILL_INTERVAL_SECONDS
        )
        self._stop = asyncio.Event()
        self.stats = WorkerStats()

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        self.stats.started_at = datetime.now(UTC)
        await self._provider.start()

        logger.info(
            "enrichment_worker_started",
            provider=self._provider.name,
            batch_limit=self._batch_limit,
            poll_interval_seconds=self._poll_interval,
            batch_size=self._provider.batch_size,
        )

        listener = asyncio.create_task(
            self._listen_for_discoveries(), name="enrichment-listener"
        )
        try:
            await self._backfill_missing_state()
            await self._refresh_loop()
        finally:
            listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listener
            await self._provider.close()
            logger.info("enrichment_worker_stopped", **self.stats.as_dict())

    # --- Discovery intake ---------------------------------------------------

    async def _listen_for_discoveries(self) -> None:
        """Enrol newly discovered tokens the moment the scanner publishes them."""
        attempt = 0
        while not self._stop.is_set():
            pubsub = None
            try:
                pubsub = get_redis().pubsub()
                await pubsub.subscribe(settings.token_channel)
                attempt = 0
                logger.info("enrichment_listener_subscribed", channel=settings.token_channel)

                async for message in pubsub.listen():
                    if self._stop.is_set():
                        break
                    if message.get("type") != "message":
                        continue
                    await self._handle_discovery_message(message)

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                attempt += 1
                self.stats.listener_reconnects += 1
                delay = min(2.0**attempt, 30.0)
                logger.warning(
                    "enrichment_listener_reconnect",
                    error=str(exc),
                    error_type=type(exc).__name__,
                    attempt=attempt,
                    delay_seconds=delay,
                )
                await asyncio.sleep(delay)
            finally:
                if pubsub is not None:
                    with contextlib.suppress(Exception):
                        await pubsub.aclose()  # type: ignore[no-untyped-call]

    async def _handle_discovery_message(self, message: dict[str, Any]) -> None:
        """Process exactly one discovery, and never let it kill the listener.

        Previously only JSON errors were caught here; anything the database
        raised escaped to the reconnect handler, which tore down the whole
        subscription. A single message naming a token that did not exist —
        which is what a test run publishing onto a shared channel produces —
        cost every subsequent discovery until the resubscribe completed, then
        repeated.

        The blast radius of a bad message is now that message. The database
        queue is the durable path regardless: a discovery missed here is picked
        up by the backfill sweep within five minutes, so swallowing the failure
        loses latency, not tokens.
        """
        self.stats.discovery_messages += 1
        try:
            payload = json.loads(message["data"])
            mint = payload.get("mint_address")
        except (ValueError, TypeError, AttributeError, KeyError):
            self.stats.discovery_messages_failed += 1
            logger.warning(
                "enrichment_discovery_malformed",
                reason="payload is not JSON with a mint_address",
                raw=str(message.get("data"))[:200],
            )
            return
        if not mint:
            self.stats.discovery_messages_failed += 1
            logger.warning("enrichment_discovery_malformed", reason="no mint_address")
            return

        try:
            async with SessionFactory() as session:
                service = MarketEnrichmentService(
                    session, self._provider, scheduler=self._scheduler
                )
                if await service.register_token(mint):
                    self.stats.tokens_registered += 1
                await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.stats.discovery_messages_failed += 1
            logger.warning(
                "enrichment_discovery_failed",
                mint=mint,
                error=str(exc),
                error_type=type(exc).__name__,
                failed_total=self.stats.discovery_messages_failed,
                detail=(
                    "This discovery was skipped. The backfill sweep will enrol "
                    "the token if it genuinely exists."
                ),
            )

    async def _backfill_missing_state(self) -> None:
        """Enrol any discovered token that has no scheduling row yet."""
        total = 0
        while True:
            async with SessionFactory() as session:
                service = MarketEnrichmentService(
                    session, self._provider, scheduler=self._scheduler
                )
                created = await service.backfill_registrations(limit=500)
                await session.commit()
            total += created
            if created == 0:
                break
        if total:
            logger.info("enrichment_backfill_completed", tokens=total)

    # --- Refresh loop -------------------------------------------------------

    async def _refresh_loop(self) -> None:
        last_backfill = time.monotonic()

        while not self._stop.is_set():
            processed = 0
            try:
                # Re-sweep periodically. The Redis listener is the fast path,
                # not a guarantee: it can miss events during a Redis restart or
                # if this worker was down, and a startup-only sweep would leave
                # those tokens orphaned indefinitely.
                if time.monotonic() - last_backfill >= self._backfill_interval:
                    await self._backfill_missing_state()
                    last_backfill = time.monotonic()

                processed = await self._run_cycle()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("enrichment_cycle_failed")

            # Only idle when there was nothing to do; a full batch means the
            # backlog is non-empty and should be drained immediately.
            if processed < self._batch_limit:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=self._poll_interval)

    async def _run_cycle(self) -> int:
        """Claim one batch and enrich it. Returns how many tokens were processed."""
        async with SessionFactory() as session:
            service = MarketEnrichmentService(
                session, self._provider, scheduler=self._scheduler
            )
            states = await service.claim_batch(limit=self._batch_limit)
            if not states:
                await session.commit()
                return 0

            # Provider batch limit is smaller than our claim size, so chunk.
            chunk_size = max(1, self._provider.batch_size)
            total = 0
            for start in range(0, len(states), chunk_size):
                chunk = states[start : start + chunk_size]
                outcome = await service.enrich(chunk)

                self.stats.tokens_refreshed += outcome.requested
                self.stats.snapshots_written += outcome.snapshots_written
                self.stats.without_market += outcome.without_market
                self.stats.failures += outcome.failed
                self.stats.deferred += outcome.deferred
                self.stats.dead_lettered += outcome.dead_lettered
                if outcome.degraded:
                    self.stats.degraded_cycles += 1
                total += outcome.requested

            mints = [state.mint_address for state in states]
            # TX-1 ends here. Snapshots are durable from this point, whatever
            # scoring does next.
            await session.commit()
            self.stats.cycles += 1

        await self._score_batch(mints)
        await self._collect_curves(mints)
        await self._detect_opportunities(mints)
        return total

    # --- Scoring (TX-2) -----------------------------------------------------

    async def _score_batch(self, mints: Sequence[str]) -> None:
        """Score the batch that was just enriched, in its own transaction.

        Deliberately outside the enrichment transaction. `claim_due` holds row
        locks on `token_enrichment_state` until TX-1 commits, so scoring inside
        it would extend that lock across every worker replica for the sake of a
        computation that is derived and recomputable. Running afterwards costs a
        crash window in which a snapshot exists without a score, which the sweep
        closes anyway - it has to, for deploys and restarts.

        Failure here is contained: it is logged and the cycle continues. The
        snapshots are already committed, and the sweep will pick the token up.
        """
        if not settings.FEATURE_AI_SCORING_ENABLED or not mints:
            return

        try:
            async with SessionFactory() as session:
                service = TokenScoringService(session)
                outcome = await service.score_mints(mints, now=datetime.now(UTC))
                await session.commit()
        except Exception:
            self.stats.scoring_failures += 1
            logger.exception("scoring_cycle_failed", tokens=len(mints))
            return

        self.stats.tokens_scored += outcome.scored
        self.stats.score_history_written += outcome.history_written

        # After the commit, never before: an event published from inside the
        # transaction can describe a score that never landed.
        if outcome.events:
            await publish_score_events(outcome.events)
            self.stats.score_events_published += len(outcome.events)

    # --- Bonding curve collection (TX-3) ------------------------------------

    async def _collect_curves(self, mints: Sequence[str]) -> None:
        """Read the bonding curve for the batch that was just enriched.

        Runs **before** detection so a curve observation written now is visible
        to the providers evaluated moments later — that ordering is what lets
        near graduation read a curve position from the same cycle rather than
        always trailing it by one.

        Its own transaction, and contained: the chain and DexScreener are
        independent sources, so a Helius outage must cost the curve series and
        nothing else. The snapshots are already durable by this point.
        """
        if not settings.FEATURE_CURVE_COLLECTION_ENABLED or not mints:
            return

        try:
            async with SessionFactory() as session:
                collector = BondingCurveCollector(session)
                outcome = await collector.collect(
                    list(mints)[: settings.CURVE_COLLECTION_BATCH_LIMIT],
                    now=datetime.now(UTC),
                )
                await session.commit()
        except Exception:
            self.stats.curve_failures += 1
            logger.exception("curve_collection_failed", tokens=len(mints))
            return

        self.stats.curve_reads += outcome.fetched
        self.stats.curve_snapshots += outcome.written
        self.stats.curve_unparsable += outcome.unparsable

    # --- Opportunity detection (TX-4) ---------------------------------------

    async def _detect_opportunities(self, mints: Sequence[str]) -> None:
        """Run signal detection over the batch that was just enriched.

        This is what makes detection event-driven rather than a scan: the
        engine evaluates exactly the tokens whose observations just changed, on
        the tiered cadence the scheduler already paces. There is no recurring
        sweep over the token universe, and work is proportional to change
        rather than to table size (ARCHITECTURE_DECISIONS.md AD-12).

        Its own transaction, after scoring, for the same reason scoring is
        separate from enrichment: `claim_due` holds row locks until TX-1
        commits, and detection is derived and recomputable. A failure is
        contained and logged — the snapshots are already durable, and the next
        refresh of the same token re-evaluates it.
        """
        if not settings.FEATURE_OPPORTUNITY_ENGINE_ENABLED or not mints:
            return

        try:
            async with SessionFactory() as session:
                engine = OpportunityEngine(session)
                outcome = await engine.detect(mints, now=datetime.now(UTC))
                await session.commit()
        except Exception:
            self.stats.opportunity_failures += 1
            logger.exception("opportunity_cycle_failed", tokens=len(mints))
            return

        self.stats.opportunities_opened += outcome.opportunities_opened
        self.stats.opportunity_signals += outcome.signals_added
        self.stats.opportunity_events += outcome.events_recorded


async def run_worker() -> None:
    """Entrypoint used by the enrichment process."""
    import signal

    from app.core.redis import close_redis, init_redis

    worker = MarketEnrichmentWorker()
    await init_redis()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, worker.stop)

    try:
        await worker.run()
    finally:
        await close_redis()
