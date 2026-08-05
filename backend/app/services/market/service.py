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
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.market import TokenEnrichmentState
from app.repositories.market import EnrichmentStateRepository, MarketSnapshotRepository
from app.repositories.token import TokenRepository
from app.services.market.providers.base import (
    MarketData,
    MarketDataProvider,
    ProviderError,
    ProviderUnavailableError,
)
from app.services.market.scheduler import RefreshScheduler

logger = get_logger(__name__)


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
        )
        if created is not None:
            logger.info("enrichment_token_registered", mint=mint_address)
        return created is not None

    async def backfill_registrations(self, *, limit: int = 500) -> int:
        """Enrol tokens discovered while the worker was not running.

        Without this, a worker restart would silently orphan everything the
        scanner found in the meantime.
        """
        return await self.states.backfill_missing(limit=limit)

    async def claim_batch(self, *, limit: int | None = None) -> Sequence[TokenEnrichmentState]:
        return await self.states.claim_due(
            now=datetime.now(UTC), limit=limit or settings.ENRICHMENT_BATCH_LIMIT
        )

    async def enrich(self, states: Sequence[TokenEnrichmentState]) -> EnrichmentOutcome:
        """Refresh one batch of tokens and persist the results.

        A provider outage degrades rather than fails: every token in the batch
        is rescheduled with backoff and the worker keeps running. Discovery is
        never affected — it is a different process entirely.
        """
        if not states:
            return EnrichmentOutcome(0, 0, 0, 0, 0)

        mints = [state.mint_address for state in states]
        now = datetime.now(UTC)

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
            results = await self.provider.fetch_many(mints)
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

        if unavailable:
            return await self._defer(
                states, now=now, retry_after_seconds=retry_after, error=error
            )

        snapshot_rows: list[dict[str, Any]] = []
        written = 0
        without_market = 0
        failed = 0
        dead_lettered = 0

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
            elif succeeded:
                without_market += 1
            else:
                failed += 1

            decision = self.scheduler.decide(
                now=now,
                discovered_at=token_discovered_at,
                consecutive_failures=(state.consecutive_failures + 1) if not succeeded else 0,
                consecutive_empty=(
                    (state.consecutive_empty + 1) if succeeded and not had_data else 0
                ),
                # The lane the priority beat placed this token in. Read from the
                # row rather than recomputed here: membership is decided in one
                # place, and the worker only honours it.
                priority=(settings.FEATURE_PRIORITY_ENRICHMENT_ENABLED and state.priority > 0),
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
