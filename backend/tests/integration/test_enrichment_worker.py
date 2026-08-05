"""Enrichment service and worker tests.

The provider is faked so failure modes — outage, empty results, partial data —
are reproducible without touching the network.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market import (
    EnrichmentStatus,
    TokenEnrichmentState,
    TokenMarketSnapshot,
    TradingStatus,
)
from app.repositories.market import EnrichmentStateRepository
from app.repositories.token import TokenRepository
from app.services.market.providers.base import (
    MarketData,
    MarketDataProvider,
    ProviderError,
    ProviderHealth,
    ProviderUnavailableError,
)
from app.services.market.scheduler import RefreshScheduler
from app.services.market.service import MarketEnrichmentService
from app.services.market.worker import MarketEnrichmentWorker

pytestmark = pytest.mark.integration


class FakeProvider(MarketDataProvider):
    name = "fake"
    batch_size = 30

    def __init__(
        self,
        *,
        data: dict[str, MarketData] | None = None,
        raises: Exception | None = None,
    ) -> None:
        self.data = data or {}
        self.raises = raises
        self.calls: list[list[str]] = []

    async def fetch_many(self, mint_addresses: Sequence[str]) -> dict[str, MarketData]:
        self.calls.append(list(mint_addresses))
        if self.raises is not None:
            raise self.raises
        return {m: self.data[m] for m in mint_addresses if m in self.data}

    async def health(self) -> ProviderHealth:
        return ProviderHealth(name=self.name, available=True, circuit_state="closed")


def _market(mint: str, **overrides: Any) -> MarketData:
    values: dict[str, Any] = {
        "mint_address": mint,
        "price_usd": Decimal("0.0000042"),
        "liquidity_usd": Decimal("12345.67"),
        "fully_diluted_valuation": Decimal("99000"),
        "market_cap": Decimal("88000"),
        "volume_24h": Decimal("5000"),
        "volume_1h": Decimal("400"),
        "volume_5m": Decimal("30"),
        "buy_count_24h": 120,
        "sell_count_24h": 80,
        "dex_name": "pumpfun",
        "trading_pair": "TKN/SOL",
        "pool_address": "pool123",
        "trading_status": TradingStatus.TRADING,
        "is_verified": True,
        "provider": "fake",
        "provider_latency_ms": 42,
        "observed_at": datetime.now(UTC),
    }
    values.update(overrides)
    return MarketData(**values)


async def _token_with_state(
    session: AsyncSession, mint: str, *, discovered_at: datetime | None = None
) -> TokenEnrichmentState:
    token = await TokenRepository(session).insert_if_absent(
        {
            "mint_address": mint,
            "signature": f"sig-{mint}",
            "slot": 1,
            "discovered_at": discovered_at or datetime.now(UTC),
        }
    )
    assert token is not None
    state = await EnrichmentStateRepository(session).ensure_state(
        token_id=token.id,
        mint_address=mint,
        next_refresh_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    assert state is not None
    return state


async def _snapshots(session: AsyncSession, mint: str) -> list[TokenMarketSnapshot]:
    result = await session.execute(
        select(TokenMarketSnapshot).where(TokenMarketSnapshot.mint_address == mint)
    )
    return list(result.scalars().all())


# --- Service -----------------------------------------------------------------


async def test_enrichment_writes_a_snapshot(db_session: AsyncSession) -> None:
    state = await _token_with_state(db_session, "MintEnrich")
    provider = FakeProvider(data={"MintEnrich": _market("MintEnrich")})
    service = MarketEnrichmentService(db_session, provider)

    outcome = await service.enrich([state])

    assert outcome.snapshots_written == 1
    assert outcome.failed == 0

    rows = await _snapshots(db_session, "MintEnrich")
    assert len(rows) == 1
    assert rows[0].price_usd == Decimal("0.0000042")
    assert rows[0].dex_name == "pumpfun"
    assert rows[0].trading_status is TradingStatus.TRADING
    assert rows[0].provider == "fake"


async def test_repeated_enrichment_accumulates_history(db_session: AsyncSession) -> None:
    """Every refresh appends; nothing is overwritten."""
    state = await _token_with_state(db_session, "MintAccum")
    provider = FakeProvider(data={"MintAccum": _market("MintAccum")})
    service = MarketEnrichmentService(db_session, provider)

    for _ in range(3):
        state.next_refresh_at = datetime.now(UTC) - timedelta(seconds=1)
        await service.enrich([state])

    assert len(await _snapshots(db_session, "MintAccum")) == 3
    assert state.total_snapshots == 3


async def test_token_without_market_is_not_snapshotted_but_is_rescheduled(
    db_session: AsyncSession,
) -> None:
    """An unindexed mint is normal: no snapshot, no failure, try again later."""
    state = await _token_with_state(db_session, "MintNoPool")
    service = MarketEnrichmentService(db_session, FakeProvider(data={}))

    outcome = await service.enrich([state])

    assert outcome.snapshots_written == 0
    assert outcome.without_market == 1
    assert outcome.failed == 0
    assert await _snapshots(db_session, "MintNoPool") == []
    assert state.consecutive_empty == 1
    assert state.consecutive_failures == 0
    assert state.next_refresh_at > datetime.now(UTC)


async def test_provider_outage_degrades_without_raising(db_session: AsyncSession) -> None:
    """Graceful degradation: the worker keeps running through an outage."""
    state = await _token_with_state(db_session, "MintDown")
    service = MarketEnrichmentService(
        db_session, FakeProvider(raises=ProviderError("provider exploded"))
    )

    outcome = await service.enrich([state])

    assert outcome.degraded is True
    assert outcome.failed == 1
    assert state.consecutive_failures == 1
    assert state.last_error is not None


class TestAProviderOutageIsNotTheTokensFault:
    """The incident of 2026-08-05, and the rules that now prevent it.

    DexScreener's circuit opened for a 60-second cooldown. Every rejected batch
    was counted as a failure against every token in it, and because a rejection
    returns in zero milliseconds the worker re-claimed and re-rejected at full
    speed — so the ten-failure dead-letter budget was spent in seconds. 163 of
    the 200 tokens in the priority enrichment lane were parked by an outage they
    had nothing to do with, and nothing ever brought them back.

    The distinction these tests defend is simple: **a token cannot be judged by
    a call that never left the process.**
    """

    async def test_an_unavailable_provider_costs_the_token_nothing(
        self, db_session: AsyncSession
    ) -> None:
        state = await _token_with_state(db_session, "MintCircuit")
        state.consecutive_failures = 3
        service = MarketEnrichmentService(
            db_session, FakeProvider(raises=ProviderUnavailableError("circuit open"))
        )

        outcome = await service.enrich([state])

        assert outcome.degraded is True
        # Reported as deferred, not failed. The two are different facts.
        assert outcome.deferred == 1
        assert outcome.failed == 0
        # And nothing about the token moved: no failure, no attempt, no error.
        assert state.consecutive_failures == 3
        assert state.status is EnrichmentStatus.ACTIVE

    async def test_an_outage_can_never_dead_letter_a_token(
        self, db_session: AsyncSession
    ) -> None:
        """The exact shape of the incident: a token one failure short of the
        threshold, hammered by a hundred circuit rejections."""
        state = await _token_with_state(db_session, "MintNearThreshold")
        state.consecutive_failures = 9
        service = MarketEnrichmentService(
            db_session, FakeProvider(raises=ProviderUnavailableError("circuit open"))
        )

        for _ in range(100):
            state.next_refresh_at = datetime.now(UTC) - timedelta(seconds=1)
            await service.enrich([state])

        assert state.status is EnrichmentStatus.ACTIVE
        assert state.consecutive_failures == 9

    async def test_the_batch_is_pushed_back_by_the_remaining_cooldown(
        self, db_session: AsyncSession
    ) -> None:
        """What stops the spin. A rejection costs nothing to produce, so
        without this the worker re-claims the same batch immediately and burns
        the whole budget in one second."""
        state = await _token_with_state(db_session, "MintBackoff")
        service = MarketEnrichmentService(
            db_session,
            FakeProvider(
                raises=ProviderUnavailableError("circuit open", retry_after_seconds=45.0)
            ),
        )

        await service.enrich([state])

        assert state.next_refresh_at >= datetime.now(UTC) + timedelta(seconds=40)

    async def test_a_breaker_reporting_no_cooldown_still_defers(
        self, db_session: AsyncSession
    ) -> None:
        """The floor. A cooldown of nearly zero would otherwise reschedule the
        batch into the past and spin exactly as before."""
        state = await _token_with_state(db_session, "MintNoCooldown")
        service = MarketEnrichmentService(
            db_session,
            FakeProvider(
                raises=ProviderUnavailableError("circuit open", retry_after_seconds=0.0)
            ),
        )

        await service.enrich([state])

        assert state.next_refresh_at > datetime.now(UTC) + timedelta(seconds=5)

    async def test_a_real_provider_error_is_still_the_tokens_failure(
        self, db_session: AsyncSession
    ) -> None:
        """The fix must not swallow genuine failures. A call that was made and
        went wrong is evidence about the token; a call never made is not."""
        state = await _token_with_state(db_session, "MintRealError")
        service = MarketEnrichmentService(
            db_session, FakeProvider(raises=ProviderError("provider exploded"))
        )

        outcome = await service.enrich([state])

        assert outcome.failed == 1
        assert outcome.deferred == 0
        assert state.consecutive_failures == 1


async def test_repeated_failures_dead_letter_the_token(db_session: AsyncSession) -> None:
    state = await _token_with_state(db_session, "MintDeadLetter")
    service = MarketEnrichmentService(db_session, FakeProvider(raises=ProviderError("boom")))

    for _ in range(12):
        state.next_refresh_at = datetime.now(UTC) - timedelta(seconds=1)
        await service.enrich([state])

    assert state.status is EnrichmentStatus.DEAD_LETTER
    # A dead-lettered token stops consuming provider budget.
    assert (
        await EnrichmentStateRepository(db_session).claim_due(
            now=datetime.now(UTC) + timedelta(days=2), limit=10
        )
        == []
    )


async def test_empty_batch_short_circuits(db_session: AsyncSession) -> None:
    provider = FakeProvider()
    outcome = await MarketEnrichmentService(db_session, provider).enrich([])

    assert outcome.requested == 0
    assert provider.calls == [], "must not call the provider with nothing to do"


async def test_batch_enrichment_uses_a_single_provider_call(
    db_session: AsyncSession,
) -> None:
    states = [await _token_with_state(db_session, f"MintBatch{n}") for n in range(5)]
    data = {state.mint_address: _market(state.mint_address) for state in states}
    provider = FakeProvider(data=data)

    outcome = await MarketEnrichmentService(db_session, provider).enrich(states)

    assert outcome.snapshots_written == 5
    assert len(provider.calls) == 1, "batching must not degenerate into per-token calls"


async def test_scheduler_tier_is_recorded(db_session: AsyncSession) -> None:
    fresh = await _token_with_state(db_session, "MintFresh")
    old = await _token_with_state(
        db_session, "MintOld", discovered_at=datetime.now(UTC) - timedelta(days=5)
    )
    provider = FakeProvider(
        data={s.mint_address: _market(s.mint_address) for s in (fresh, old)}
    )

    await MarketEnrichmentService(db_session, provider).enrich([fresh, old])

    assert fresh.tier == "fresh"
    assert old.tier == "old"
    # Old tokens are scheduled much further out than fresh ones.
    assert old.next_refresh_at > fresh.next_refresh_at


async def test_register_token_enrols_it(db_session: AsyncSession) -> None:
    await TokenRepository(db_session).insert_if_absent(
        {"mint_address": "MintReg", "signature": "s", "slot": 1}
    )
    service = MarketEnrichmentService(db_session, FakeProvider())

    assert await service.register_token("MintReg") is True
    assert await service.register_token("MintReg") is False, "registration is idempotent"


async def test_register_unknown_token_is_ignored(db_session: AsyncSession) -> None:
    service = MarketEnrichmentService(db_session, FakeProvider())
    assert await service.register_token("NoSuchMint") is False


async def test_backfill_registers_orphaned_tokens(db_session: AsyncSession) -> None:
    for n in range(3):
        await TokenRepository(db_session).insert_if_absent(
            {"mint_address": f"MintBF{n}", "signature": f"s{n}", "slot": 1}
        )
    service = MarketEnrichmentService(db_session, FakeProvider())

    assert await service.backfill_registrations(limit=100) == 3


# --- Worker ------------------------------------------------------------------


async def test_worker_cycle_claims_and_enriches(
    client: Any, test_session_factory: Any
) -> None:
    """The worker opens its own sessions, so it needs committed data.

    `test_session_factory` repoints the worker at the test database. Without it
    the worker would hit the development database, where a live enrichment
    worker is also claiming rows — making this test race and flake.
    """
    sessions = test_session_factory

    mint = "MintWorkerCycle"
    async with sessions() as session:
        await _token_with_state(session, mint)
        await session.commit()

    try:
        provider = FakeProvider(data={mint: _market(mint)})
        worker = MarketEnrichmentWorker(provider=provider, scheduler=RefreshScheduler())

        processed = await worker._run_cycle()

        assert processed == 1
        assert worker.stats.snapshots_written == 1
        assert provider.calls == [[mint]]

        async with sessions() as session:
            rows = await _snapshots(session, mint)
            assert len(rows) == 1
            assert rows[0].price_usd == Decimal("0.0000042")
    finally:
        async with sessions() as session:
            for row in await _snapshots(session, mint):
                await session.delete(row)
            state_row = await EnrichmentStateRepository(session).get_by_mint(mint)
            if state_row is not None:
                await session.delete(state_row)
            token = await TokenRepository(session).get_by_mint(mint)
            if token is not None:
                await session.delete(token)
            await session.commit()


async def test_worker_cycle_with_nothing_due_is_a_no_op(
    client: Any, test_session_factory: Any
) -> None:
    provider = FakeProvider()
    worker = MarketEnrichmentWorker(provider=provider)

    assert await worker._run_cycle() == 0
    assert provider.calls == []


async def test_worker_chunks_to_the_provider_batch_size(
    db_session: AsyncSession, client: Any
) -> None:
    """Claim size may exceed what the provider accepts per call."""
    states = [await _token_with_state(db_session, f"MintChunk{n}") for n in range(5)]
    provider = FakeProvider(data={s.mint_address: _market(s.mint_address) for s in states})
    provider.batch_size = 2
    service = MarketEnrichmentService(db_session, provider)

    for start in range(0, len(states), provider.batch_size):
        await service.enrich(states[start : start + provider.batch_size])

    assert [len(call) for call in provider.calls] == [2, 2, 1]


async def test_worker_backfills_orphans_periodically(
    client: Any, test_session_factory: Any
) -> None:
    """The Redis listener is the fast path, not a guarantee.

    Tokens discovered while the worker was down — or during a Redis blip — have
    no scheduling row. A startup-only sweep would leave them orphaned until
    someone restarted the worker, so the sweep also runs on an interval.
    """
    sessions = test_session_factory
    mints = [f"MintOrphaned{n}" for n in range(3)]

    async with sessions() as session:
        for mint in mints:
            await TokenRepository(session).insert_if_absent(
                {"mint_address": mint, "signature": f"sig-{mint}", "slot": 1}
            )
        await session.commit()

    try:
        worker = MarketEnrichmentWorker(provider=FakeProvider(), backfill_interval=0.0)

        async with sessions() as session:
            repo = EnrichmentStateRepository(session)
            for mint in mints:
                assert await repo.get_by_mint(mint) is None

        await worker._backfill_missing_state()

        async with sessions() as session:
            repo = EnrichmentStateRepository(session)
            for mint in mints:
                assert await repo.get_by_mint(mint) is not None, f"{mint} was orphaned"
    finally:
        async with sessions() as session:
            for mint in mints:
                state = await EnrichmentStateRepository(session).get_by_mint(mint)
                if state is not None:
                    await session.delete(state)
                token = await TokenRepository(session).get_by_mint(mint)
                if token is not None:
                    await session.delete(token)
            await session.commit()
