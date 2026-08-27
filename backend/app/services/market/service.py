"""Market enrichment service.

Owns the business rules: what "enriching a token" means, how a provider result
becomes a snapshot, when a token is rescheduled, and when it is dead-lettered.
Knows nothing about HTTP, WebSockets, or the vendor's JSON — it talks to a
`MarketDataProvider` and to repositories.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.market import sanity
from app.core.logging import get_logger
from app.models.market import (
    LANE_DISPLAY,
    LANE_NORMAL,
    LANE_NURSERY,
    TokenEnrichmentState,
    TradingStatus,
)
from app.repositories.market import EnrichmentStateRepository, MarketSnapshotRepository
from app.repositories.token import TokenRepository
from app.services.market.providers.base import (
    MarketData,
    MarketDataProvider,
    ProviderError,
    ProviderUnavailableError,
)
from app.services.market.scheduler import RefreshScheduler
from app.services.token_images import TokenImageResolver

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class FetchedBatch:
    """One chunk's provider answer, before anything is written down.

    Carries the outage flag separately from the error text because the two
    lead to different places: an outage defers the batch untouched, while a
    provider error is charged to the tokens that were actually asked about.
    """

    results: dict[str, MarketData]
    error: str | None
    degraded: bool
    unavailable: bool
    retry_after_seconds: float | None
    latency_ms: int


@dataclass(frozen=True, slots=True)
class EnrichmentOutcome:
    requested: int
    snapshots_written: int
    without_market: int
    failed: int
    dead_lettered: int
    provider_latency_ms: int | None = None
    degraded: bool = False
    #: Tokens the provider was never asked about, because it was unavailable.
    #: Counted apart from `failed` on purpose — these carry no blame and no
    #: consequence for the token, and merging them would hide the difference.
    deferred: int = 0
    #: Mints that gained a committed market snapshot in this batch.
    refreshed_mints: tuple[str, ...] = ()


class MarketEnrichmentService:
    def __init__(
        self,
        session: AsyncSession,
        provider: MarketDataProvider,
        *,
        scheduler: RefreshScheduler | None = None,
    ) -> None:
        self.session = session
        self.provider = provider
        self.scheduler = scheduler or RefreshScheduler()
        self.snapshots = MarketSnapshotRepository(session)
        self.states = EnrichmentStateRepository(session)
        self.tokens = TokenRepository(session)

    async def register_token(self, mint_address: str) -> bool:
        """Enrol a newly discovered token in the refresh schedule.

        Called by the worker's discovery listener. Idempotent.
        """
        token = await self.tokens.get_by_mint(mint_address)
        if token is None:
            logger.warning("enrichment_register_unknown_token", mint=mint_address)
            return False

        created = await self.states.ensure_state(
            token_id=token.id,
            mint_address=token.mint_address,
            # Due immediately: a brand-new token is the most interesting one.
            next_refresh_at=datetime.now(UTC),
            # Straight into the nursery: discovery itself is the qualification,
            # which is what breaks the needs-observations-to-be-interesting
            # loop. Deliberately no capacity check here — one count query per
            # discovery buys nothing, because the membership beat trims any
            # overshoot to `ENRICHMENT_NURSERY_MAX_TOKENS` within a minute and
            # the claim query's batch limit bounds a burst's damage meanwhile.
            priority=(
                LANE_NURSERY if settings.ENRICHMENT_NURSERY_MAX_TOKENS > 0 else LANE_NORMAL
            ),
        )
        if created is not None:
            logger.info("enrichment_token_registered", mint=mint_address)
        # A raw scanner event only enrols normal enrichment.  Generation 6
        # quote acceleration is tied to the canonical Track Record admission,
        # never to raw discovery.
        await self.states.prioritize_unquoted_track_record_candidates(now=datetime.now(UTC))
        if token.image_url is None and token.metadata_uri:
            await self._refresh_token_image(token)
        return created is not None

    async def backfill_registrations(self, *, limit: int = 500) -> int:
        """Enrol tokens discovered while the worker was not running.

        Without this, a worker restart would silently orphan everything the
        scanner found in the meantime.
        """
        created = await self.states.backfill_missing(limit=limit)
        await self.states.prioritize_unquoted_track_record_candidates(now=datetime.now(UTC))
        return created

    async def backfill_missing_images(self, *, limit: int = 50) -> int:
        """Resolve token images for existing rows, idempotently and by exact mint row."""
        tokens = await self.tokens.list_missing_images(limit=limit)
        resolved = 0
        for token in tokens:
            if await self._refresh_token_image(token):
                resolved += 1
        return resolved

    async def claim_batch(
        self, *, limit: int | None = None, min_priority: int | None = None
    ) -> Sequence[TokenEnrichmentState]:
        return await self.states.claim_due(
            now=datetime.now(UTC),
            limit=limit or settings.ENRICHMENT_BATCH_LIMIT,
            min_priority=min_priority,
        )

    async def _refresh_token_image(self, token: Any) -> bool:
        async with TokenImageResolver() as resolver:
            resolution = await resolver.resolve(token.metadata_uri)
        if resolution is None:
            return False
        await self.tokens.update_image_url(token, image_url=resolution.image_url)
        logger.info(
            "token_image_resolved",
            mint=token.mint_address,
            source=resolution.source,
            image_url=resolution.image_url,
        )
        return True

    async def fetch(self, mints: Sequence[str]) -> FetchedBatch:
        """Ask the provider about one chunk. **No database access at all.**

        Split out of `enrich` so the worker can issue several chunks'
        requests concurrently while still persisting them one at a time: the
        session is not concurrency-safe, but the provider is (one HTTP call per
        chunk, a pooled client, and a breaker whose counters are updated
        without awaiting). Sequential fetching made the cycle latency-bound —
        four chunks at ~1.5s each — which capped the whole worker at ~720
        refreshes a minute against lane demand of 1,400.
        """
        logger.info("refresh_started", tokens=len(mints), provider=self.provider.name)
        started = time.perf_counter()

        results: dict[str, MarketData] = {}
        error: str | None = None
        degraded = False
        # A separate flag, not `retry_after_seconds is not None`: a breaker that
        # reports no cooldown is still an outage, and conflating the two would
        # send the batch down the failure path — which is the whole bug.
        unavailable = False
        retry_after: float | None = None

        try:
            results = await self.provider.fetch_many(list(mints))
        except ProviderUnavailableError as exc:
            # Circuit is open. **No call was made on any token's behalf**, so
            # this is not evidence about any token in the batch. It is recorded
            # as a deferral below rather than as a failure — see `_defer`.
            error = str(exc)
            degraded = True
            unavailable = True
            retry_after = exc.retry_after_seconds
            logger.warning("refresh_degraded", reason="provider_unavailable", detail=error)
        except ProviderError as exc:
            error = str(exc)
            degraded = True
            logger.warning("refresh_failed", provider=self.provider.name, error=error)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            degraded = True
            logger.exception("refresh_failed_unexpected", provider=self.provider.name)

        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "provider_latency",
            provider=self.provider.name,
            latency_ms=latency_ms,
            requested=len(mints),
            returned=len(results),
        )
        return FetchedBatch(
            results=results,
            error=error,
            degraded=degraded,
            unavailable=unavailable,
            retry_after_seconds=retry_after,
            latency_ms=latency_ms,
        )

    async def enrich(
        self,
        states: Sequence[TokenEnrichmentState],
        *,
        fetched: FetchedBatch | None = None,
    ) -> EnrichmentOutcome:
        """Refresh one batch of tokens and persist the results.

        A provider outage degrades rather than fails: every token in the batch
        is rescheduled with backoff and the worker keeps running. Discovery is
        never affected — it is a different process entirely.

        `fetched` lets a caller supply a result it already obtained from
        `fetch`; omitted, the provider is called here exactly as before.
        """
        if not states:
            return EnrichmentOutcome(0, 0, 0, 0, 0)

        mints = [state.mint_address for state in states]
        now = datetime.now(UTC)

        batch = fetched if fetched is not None else await self.fetch(mints)
        results = batch.results
        error = batch.error
        degraded = batch.degraded
        unavailable = batch.unavailable
        retry_after = batch.retry_after_seconds
        latency_ms = batch.latency_ms

        if unavailable:
            return await self._defer(
                states, now=now, retry_after_seconds=retry_after, error=error
            )

        snapshot_rows: list[dict[str, Any]] = []
        written = 0
        without_market = 0
        failed = 0
        dead_lettered = 0
        refreshed_mints: list[str] = []

        # One query for the whole batch; the tier depends on each token's age.
        tokens = await self.tokens.get_many_by_mints(mints)

        for state in states:
            token = tokens.get(state.mint_address)
            token_discovered_at = token.discovered_at if token is not None else now

            succeeded = error is None
            data = results.get(state.mint_address)
            had_data = data is not None and data.has_market

            if succeeded and had_data and data is not None:
                snapshot_rows.append(self._to_snapshot_row(state, data, latency_ms=latency_ms))
                written += 1
                refreshed_mints.append(state.mint_address)
            elif succeeded:
                without_market += 1

                # If a token has persistently lost its market (dead-lettered), or is
                # ALREADY dead-lettered but held by an active subsystem, we write a
                # single INACTIVE snapshot to explicitly notify dependents rather
                # than silently dropping it from the feed forever.
                #
                # `>= LANE_DISPLAY`, not `> 0`: the repeated notification exists for
                # tokens that *have* dependents — an open paper position, a visible
                # rank, a live opportunity. A nursery token is speculative and has
                # none, so including it would append an INACTIVE row every 60
                # seconds for something nothing is watching.
                empty_count = state.consecutive_empty + 1
                if empty_count == settings.ENRICHMENT_DEAD_LETTER_THRESHOLD or (
                    empty_count > settings.ENRICHMENT_DEAD_LETTER_THRESHOLD
                    and state.priority >= LANE_DISPLAY
                ):
                    dead_data = MarketData(
                        mint_address=state.mint_address,
                        trading_status=TradingStatus.INACTIVE,
                        observed_at=now,
                        provider=self.provider.name,
                    )
                    snapshot_rows.append(
                        self._to_snapshot_row(state, dead_data, latency_ms=latency_ms)
                    )
                    written += 1
            else:
                failed += 1

            decision = self.scheduler.decide(
                now=now,
                discovered_at=token_discovered_at,
                consecutive_failures=(state.consecutive_failures + 1) if not succeeded else 0,
                consecutive_empty=(
                    (state.consecutive_empty + 1) if succeeded and not had_data else 0
                ),
                # The lane the membership beats placed this token in. Read from
                # the row rather than recomputed here: membership is decided in
                # one place, and the worker only honours it.
                priority=(
                    settings.FEATURE_PRIORITY_ENRICHMENT_ENABLED
                    and state.priority >= LANE_DISPLAY
                ),
                nursery=state.priority == LANE_NURSERY,
            )

            should_dead_letter = not succeeded and self.scheduler.should_dead_letter(
                state.consecutive_failures + 1,
                now=now,
                # The last moment this token demonstrably worked. Elapsed
                # failing time is a second condition on top of the count, so a
                # short outage cannot park a token whatever lane it is in.
                failing_since=state.last_success_at,
            )
            if should_dead_letter:
                dead_lettered += 1
                logger.error(
                    "enrichment_dead_lettered",
                    mint=state.mint_address,
                    consecutive_failures=state.consecutive_failures + 1,
                    last_error=error,
                )

            logger.debug(
                "scheduler_decision",
                mint=state.mint_address,
                tier=str(decision.tier),
                interval_seconds=round(decision.interval_seconds, 1),
                reason=decision.reason,
            )

            await self.states.record_result(
                state,
                now=now,
                next_refresh_at=decision.next_refresh_at,
                tier=str(decision.tier),
                succeeded=succeeded,
                had_data=had_data,
                error=error,
                dead_letter=should_dead_letter,
            )

        if snapshot_rows and settings.FEATURE_SNAPSHOT_SANITY_ENABLED:
            await self._annotate_suspects(snapshot_rows)
        if snapshot_rows:
            await self.snapshots.add_many(snapshot_rows)
            logger.info(
                "snapshot_saved", count=len(snapshot_rows), provider=self.provider.name
            )

        logger.info(
            "refresh_completed",
            requested=len(mints),
            snapshots=written,
            without_market=without_market,
            failed=failed,
            dead_lettered=dead_lettered,
            latency_ms=latency_ms,
            degraded=degraded,
        )

        return EnrichmentOutcome(
            requested=len(mints),
            snapshots_written=written,
            without_market=without_market,
            failed=failed,
            dead_lettered=dead_lettered,
            provider_latency_ms=latency_ms,
            degraded=degraded,
            refreshed_mints=tuple(refreshed_mints),
        )

    async def _defer(
        self,
        states: Sequence[TokenEnrichmentState],
        *,
        now: datetime,
        retry_after_seconds: float | None,
        error: str | None,
    ) -> EnrichmentOutcome:
        """Push a batch back when the provider was never called.

        **This is the fix for the incident of 2026-08-05.** DexScreener's
        circuit opened for a 60-second cooldown. Every rejected batch was
        counted as a failure against every token in it, and because a rejection
        returns in zero milliseconds the worker re-claimed and re-rejected at
        full speed — so the ten-failure dead-letter budget was spent in seconds.
        163 of the 200 tokens in the priority lane were dead-lettered by a
        provider blip they had nothing to do with, and dead-lettering had no
        recovery path, so they stopped refreshing permanently. Ten of the paper
        wallet's twelve holdings went dark for over an hour.

        Two things are wrong with charging that to the token and both are fixed
        here. A token cannot be judged by a call that never left the process;
        and the faster a lane refreshes, the faster it would burn its budget,
        so the tokens the product most wants fresh were the most fragile.

        So this touches **only** `next_refresh_at`, in one statement for the
        batch. No failure count, no attempt count, no dead-letter, no
        `last_attempt_at` — nothing was attempted. The delay is the breaker's
        own remaining cooldown, which is what stops the spin.
        """
        delay = max(float(retry_after_seconds or 0.0), settings.ENRICHMENT_DEFER_MIN_SECONDS)
        next_refresh_at = now + timedelta(seconds=delay)
        await self.states.defer_batch(
            [state.id for state in states], next_refresh_at=next_refresh_at
        )

        logger.info(
            "refresh_deferred",
            provider=self.provider.name,
            deferred=len(states),
            retry_in_seconds=round(delay, 1),
            detail=error,
        )
        return EnrichmentOutcome(
            requested=len(states),
            snapshots_written=0,
            without_market=0,
            # Deliberately zero. These tokens did not fail; nobody asked them.
            failed=0,
            dead_lettered=0,
            provider_latency_ms=0,
            degraded=True,
            deferred=len(states),
        )

    async def _annotate_suspects(self, rows: list[dict[str, Any]]) -> None:
        """Ingest firewall: judge each new print against its stored window.

        Annotation only — no row is dropped or altered beyond the three flag
        columns, and a failure here must never cost the batch (observation
        beats judgement, so the guard is best-effort by design).
        """
        try:
            context = await self.snapshots.recent_context(
                [row["token_id"] for row in rows],
                window_seconds=settings.SNAPSHOT_SANITY_WINDOW_SECONDS,
            )
            band = Decimal(str(settings.SNAPSHOT_SANITY_BAND))
            liq_jump = Decimal(str(settings.SNAPSHOT_SANITY_LIQUIDITY_JUMP))
            flagged = 0
            for row in rows:
                prior = [
                    sanity.PriorPoint(
                        captured_at=s.captured_at,
                        price_usd=s.price_usd,
                        liquidity_usd=s.liquidity_usd,
                        pool_address=s.pool_address,
                        suspect=s.suspect,
                    )
                    for s in context.get(row["token_id"], [])
                ]
                verdict = sanity.classify(
                    price_usd=row.get("price_usd"),
                    liquidity_usd=row.get("liquidity_usd"),
                    pool_address=row.get("pool_address"),
                    prior=prior,
                    band=band,
                    liquidity_jump=liq_jump,
                    min_prior=settings.SNAPSHOT_SANITY_MIN_PRIOR,
                )
                row["suspect"] = verdict.suspect
                row["suspect_reason"] = verdict.reason
                row["baseline_price_usd"] = verdict.baseline_price_usd
                flagged += int(verdict.suspect)
            if flagged:
                logger.info("snapshots_flagged_suspect", count=flagged, batch=len(rows))
        except Exception:
            logger.exception("snapshot_sanity_failed")

    @staticmethod
    def _to_snapshot_row(
        state: TokenEnrichmentState, data: MarketData, *, latency_ms: int
    ) -> dict[str, Any]:
        return {
            "token_id": state.token_id,
            "mint_address": state.mint_address,
            "captured_at": data.observed_at or datetime.now(UTC),
            "price_usd": data.price_usd,
            "price_native": data.price_native,
            "liquidity_usd": data.liquidity_usd,
            "fully_diluted_valuation": data.fully_diluted_valuation,
            "market_cap": data.market_cap,
            "volume_24h": data.volume_24h,
            "volume_1h": data.volume_1h,
            "volume_5m": data.volume_5m,
            "buy_count_24h": data.buy_count_24h,
            "sell_count_24h": data.sell_count_24h,
            "dex_name": data.dex_name,
            "trading_pair": data.trading_pair,
            "pool_address": data.pool_address,
            "trading_status": data.trading_status,
            "is_verified": data.is_verified,
            "provider": data.provider,
            "provider_latency_ms": data.provider_latency_ms or latency_ms,
        }
