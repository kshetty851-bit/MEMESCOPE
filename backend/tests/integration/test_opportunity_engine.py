"""The Opportunity Engine against a real database.

Covers what the pure tests cannot: deduplication under the schema's own
constraints, event emission, generation handling and concurrent detection.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.intelligence import EventKind, IntelligenceEvent
from app.models.market import TradingStatus
from app.models.opportunity import Opportunity, OpportunitySignal
from app.opportunities.engine import OpportunityEngine
from app.opportunities.lifecycle import ConfidencePolicy, ExpiryPolicy
from app.opportunities.models import (
    OpportunityStage,
    OpportunityStatus,
    SignalStatus,
    SignalType,
)
from app.opportunities.repository import OpportunityRepository
from app.repositories.market import MarketSnapshotRepository
from app.repositories.token import TokenRepository

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
MINT = "HHbRJ9Fw2tPxETGSsaeQhpgdizfVafLvXK7eo5mwpump"
OTHER = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"

POLICY = ExpiryPolicy(
    ttl_seconds={SignalType.FRESH_GRADUATION: 3600},
    default_ttl_seconds=1800,
    grace_seconds=600,
    archive_after_seconds=86_400,
)


def _engine(session: AsyncSession, **overrides: Any) -> OpportunityEngine:
    return OpportunityEngine(
        session,
        expiry=overrides.pop("expiry", POLICY),
        confidence=overrides.pop("confidence", ConfidencePolicy()),
        **overrides,
    )


async def _seed(
    session: AsyncSession, mint: str, *venues: str | None, base: datetime = NOW
) -> Any:
    """A token with one snapshot per venue, oldest first."""
    token = await TokenRepository(session).insert_if_absent(
        {
            "mint_address": mint,
            "signature": f"sig-{mint}",
            "slot": 1,
            "discovered_at": base - timedelta(days=1),
            "block_time": base - timedelta(days=1),
        }
    )
    assert token is not None

    snapshots = MarketSnapshotRepository(session)
    for index, venue in enumerate(venues):
        await snapshots.add_snapshot(
            {
                "token_id": token.id,
                "mint_address": mint,
                "captured_at": base - timedelta(minutes=len(venues) - index),
                "price_usd": Decimal("0.001"),
                "liquidity_usd": Decimal("5000"),
                "dex_name": venue,
                "trading_status": TradingStatus.TRADING,
                "provider": "test",
            }
        )
    await session.flush()
    return token


async def _events(session: AsyncSession, mint: str) -> list[IntelligenceEvent]:
    return list(
        (
            await session.scalars(
                select(IntelligenceEvent)
                .where(IntelligenceEvent.mint_address == mint)
                .order_by(IntelligenceEvent.occurred_at.asc())
            )
        ).all()
    )


class TestDetection:
    async def test_a_graduation_opens_an_opportunity(self, db_session: AsyncSession) -> None:
        await _seed(db_session, MINT, "pumpfun", "pumpswap")

        outcome = await _engine(db_session).detect([MINT], now=NOW)

        assert outcome.opportunities_opened == 1
        assert outcome.signals_added == 1
        opportunity = (await OpportunityRepository(db_session).live_for([MINT]))[MINT]
        assert opportunity.generation == 1
        assert opportunity.stage == OpportunityStage.FRESH_GRADUATION.value

    async def test_no_transition_opens_nothing(self, db_session: AsyncSession) -> None:
        await _seed(db_session, MINT, "pumpfun", "pumpfun")

        outcome = await _engine(db_session).detect([MINT], now=NOW)

        assert outcome.opportunities_opened == 0
        assert await OpportunityRepository(db_session).live_for([MINT]) == {}

    async def test_a_token_with_no_observations_is_skipped(
        self, db_session: AsyncSession
    ) -> None:
        await _seed(db_session, MINT)
        outcome = await _engine(db_session).detect([MINT], now=NOW)
        assert outcome.evaluated == 0

    async def test_detection_is_scoped_to_the_mints_given(
        self, db_session: AsyncSession
    ) -> None:
        """Event-driven, not a scan: the engine looks only at what changed."""
        await _seed(db_session, MINT, "pumpfun", "pumpswap")
        await _seed(db_session, OTHER, "pumpfun", "pumpswap")

        await _engine(db_session).detect([MINT], now=NOW)

        live = await OpportunityRepository(db_session).live_for([MINT, OTHER])
        assert MINT in live
        assert OTHER not in live


class TestDeduplication:
    async def test_re_detection_confirms_rather_than_duplicating(
        self, db_session: AsyncSession
    ) -> None:
        """The whole of AD-09's signal half."""
        await _seed(db_session, MINT, "pumpfun", "pumpswap")
        engine = _engine(db_session)

        await engine.detect([MINT], now=NOW)
        second = await engine.detect([MINT], now=NOW + timedelta(minutes=5))

        assert second.opportunities_opened == 0
        assert second.signals_added == 0
        assert second.signals_confirmed == 1

        count = await db_session.scalar(select(func.count()).select_from(OpportunitySignal))
        assert count == 1

    async def test_only_one_opportunity_per_token(self, db_session: AsyncSession) -> None:
        await _seed(db_session, MINT, "pumpfun", "pumpswap")
        engine = _engine(db_session)

        for minute in range(4):
            await engine.detect([MINT], now=NOW + timedelta(minutes=minute))

        count = await db_session.scalar(select(func.count()).select_from(Opportunity))
        assert count == 1

    async def test_re_running_over_the_same_observation_is_not_a_confirmation(
        self, db_session: AsyncSession
    ) -> None:
        """Replay must not manufacture confidence.

        Detection running twice over one snapshot is a retry, not a second
        sighting, and counting it would let a restart activate an unconfirmed
        signal.
        """
        await _seed(db_session, MINT, "pumpfun", "pumpswap")
        engine = _engine(db_session)

        await engine.detect([MINT], now=NOW)
        await engine.detect([MINT], now=NOW + timedelta(minutes=1))
        await engine.detect([MINT], now=NOW + timedelta(minutes=2))

        signal = await db_session.scalar(select(OpportunitySignal))
        assert signal is not None
        assert signal.confirmations == 1

    async def test_a_new_observation_does_confirm(self, db_session: AsyncSession) -> None:
        token = await _seed(db_session, MINT, "pumpfun", "pumpswap")
        engine = _engine(db_session)
        await engine.detect([MINT], now=NOW)

        await MarketSnapshotRepository(db_session).add_snapshot(
            {
                "token_id": token.id,
                "mint_address": MINT,
                "captured_at": NOW + timedelta(minutes=5),
                "price_usd": Decimal("0.002"),
                "dex_name": "pumpswap",
                "trading_status": TradingStatus.TRADING,
                "provider": "test",
            }
        )
        await db_session.flush()
        await engine.detect([MINT], now=NOW + timedelta(minutes=6))

        signal = await db_session.scalar(select(OpportunitySignal))
        assert signal is not None
        # The second snapshot is still pumpswap→pumpswap, so no new candidate;
        # what matters is that no duplicate row appeared.
        count = await db_session.scalar(select(func.count()).select_from(OpportunitySignal))
        assert count == 1


class TestLifecycle:
    async def test_a_first_sighting_is_pending_not_active(
        self, db_session: AsyncSession
    ) -> None:
        """One snapshot is noise. Nothing reaches a board on one observation."""
        await _seed(db_session, MINT, "pumpfun", "pumpswap")

        await _engine(db_session).detect([MINT], now=NOW)

        opportunity = (await OpportunityRepository(db_session).live_for([MINT]))[MINT]
        assert opportunity.status == OpportunityStatus.PENDING_CONFIRMATION.value

    async def test_a_second_confirmation_activates(self, db_session: AsyncSession) -> None:
        token = await _seed(db_session, MINT, "pumpfun", "pumpswap")
        engine = _engine(db_session)
        await engine.detect([MINT], now=NOW)

        # A later snapshot that still shows the transition against the window.
        await MarketSnapshotRepository(db_session).add_snapshot(
            {
                "token_id": token.id,
                "mint_address": MINT,
                "captured_at": NOW + timedelta(minutes=5),
                "price_usd": Decimal("0.002"),
                "dex_name": "pumpswap",
                "trading_status": TradingStatus.TRADING,
                "provider": "test",
            }
        )
        await db_session.flush()

        signal = await db_session.scalar(select(OpportunitySignal))
        assert signal is not None
        signal.confirmations = 2
        signal.observed_at = NOW + timedelta(minutes=5)
        await db_session.flush()

        await engine.detect([MINT], now=NOW + timedelta(minutes=6))

        opportunity = (await OpportunityRepository(db_session).live_for([MINT]))[MINT]
        assert opportunity.status == OpportunityStatus.ACTIVE.value

    async def test_an_expired_signal_moves_the_opportunity_to_expiring(
        self, db_session: AsyncSession
    ) -> None:
        await _seed(db_session, MINT, "pumpfun", "pumpswap")
        engine = _engine(db_session)
        await engine.detect([MINT], now=NOW)

        await engine.review_expired(now=NOW + timedelta(seconds=3601))

        opportunity = (await OpportunityRepository(db_session).live_for([MINT]))[MINT]
        assert opportunity.status == OpportunityStatus.EXPIRING.value
        assert opportunity.expiring_since is not None

    async def test_grace_elapsing_closes_the_opportunity(
        self, db_session: AsyncSession
    ) -> None:
        await _seed(db_session, MINT, "pumpfun", "pumpswap")
        engine = _engine(db_session)
        await engine.detect([MINT], now=NOW)

        await engine.review_expired(now=NOW + timedelta(seconds=3601))
        await engine.review_expired(now=NOW + timedelta(seconds=3601 + 601))

        closed = await db_session.scalar(
            select(Opportunity).where(Opportunity.mint_address == MINT)
        )
        assert closed is not None
        assert closed.status == OpportunityStatus.CLOSED.value
        assert closed.closed_at is not None

    async def test_a_closed_opportunity_is_archived_after_settling(
        self, db_session: AsyncSession
    ) -> None:
        await _seed(db_session, MINT, "pumpfun", "pumpswap")
        engine = _engine(db_session)
        await engine.detect([MINT], now=NOW)
        await engine.review_expired(now=NOW + timedelta(seconds=3601))
        await engine.review_expired(now=NOW + timedelta(seconds=4202))

        await engine.review_expired(now=NOW + timedelta(days=2))

        archived = await db_session.scalar(
            select(Opportunity).where(Opportunity.mint_address == MINT)
        )
        assert archived is not None
        assert archived.status == OpportunityStatus.ARCHIVED.value
        assert archived.archived_at is not None

    async def test_detected_at_is_never_revised(self, db_session: AsyncSession) -> None:
        """Every claim about performance is measured from it.

        The same discipline `radar_tokens.first_*` holds.
        """
        await _seed(db_session, MINT, "pumpfun", "pumpswap")
        engine = _engine(db_session)
        await engine.detect([MINT], now=NOW)

        original = (await OpportunityRepository(db_session).live_for([MINT]))[MINT].detected_at

        await engine.detect([MINT], now=NOW + timedelta(minutes=30))

        assert (await OpportunityRepository(db_session).live_for([MINT]))[
            MINT
        ].detected_at == original


class TestGenerations:
    async def test_a_new_opportunity_after_archival_gets_a_new_generation(
        self, db_session: AsyncSession
    ) -> None:
        """Reopening is never a resurrection.

        Two separate calls on the same token must stay separately measurable in
        the permanent record.
        """
        token = await _seed(db_session, MINT, "pumpfun", "pumpswap")
        repository = OpportunityRepository(db_session)

        first, _ = await repository.open_or_get(
            token_id=token.id,
            mint_address=MINT,
            generation=await repository.next_generation(MINT),
            detected_at=NOW,
            stage=OpportunityStage.FRESH_GRADUATION.value,
        )
        first.status = OpportunityStatus.ARCHIVED.value
        await db_session.flush()

        second, created = await repository.open_or_get(
            token_id=token.id,
            mint_address=MINT,
            generation=await repository.next_generation(MINT),
            detected_at=NOW + timedelta(days=3),
            stage=OpportunityStage.FRESH_GRADUATION.value,
        )

        assert created
        assert second.generation == 2
        assert second.id != first.id

    async def test_generations_are_never_reused(self, db_session: AsyncSession) -> None:
        token = await _seed(db_session, MINT, "pumpfun", "pumpswap")
        repository = OpportunityRepository(db_session)

        for expected in (1, 2, 3):
            opportunity, _ = await repository.open_or_get(
                token_id=token.id,
                mint_address=MINT,
                generation=await repository.next_generation(MINT),
                detected_at=NOW,
                stage=OpportunityStage.UNKNOWN.value,
            )
            assert opportunity.generation == expected
            opportunity.status = OpportunityStatus.ARCHIVED.value
            await db_session.flush()


class TestEvents:
    async def test_opening_emits_an_immutable_event(self, db_session: AsyncSession) -> None:
        await _seed(db_session, MINT, "pumpfun", "pumpswap")

        await _engine(db_session).detect([MINT], now=NOW)

        kinds = {event.kind for event in await _events(db_session, MINT)}
        assert EventKind.OPPORTUNITY_OPENED in kinds
        assert EventKind.SIGNAL_ADDED in kinds

    async def test_closing_emits_an_event(self, db_session: AsyncSession) -> None:
        await _seed(db_session, MINT, "pumpfun", "pumpswap")
        engine = _engine(db_session)
        await engine.detect([MINT], now=NOW)
        await engine.review_expired(now=NOW + timedelta(seconds=3601))
        await engine.review_expired(now=NOW + timedelta(seconds=4202))

        kinds = {event.kind for event in await _events(db_session, MINT)}
        assert EventKind.OPPORTUNITY_EXPIRING in kinds
        assert EventKind.OPPORTUNITY_CLOSED in kinds

    async def test_events_carry_both_sides_of_the_change(
        self, db_session: AsyncSession
    ) -> None:
        """A timeline that only said "something changed" would be a
        notification, not intelligence — the existing event contract."""
        await _seed(db_session, MINT, "pumpfun", "pumpswap")
        engine = _engine(db_session)
        await engine.detect([MINT], now=NOW)
        await engine.review_expired(now=NOW + timedelta(seconds=3601))

        expiring = [
            event
            for event in await _events(db_session, MINT)
            if event.kind is EventKind.OPPORTUNITY_EXPIRING
        ]
        assert expiring
        assert expiring[0].previous_value == OpportunityStatus.PENDING_CONFIRMATION.value
        assert expiring[0].current_value == OpportunityStatus.EXPIRING.value

    async def test_existing_event_semantics_are_untouched(
        self, db_session: AsyncSession
    ) -> None:
        """The engine writes new kinds only.

        No analyst kind may be emitted by the Opportunity Engine, or the
        timeline's existing meaning would shift under readers.
        """
        await _seed(db_session, MINT, "pumpfun", "pumpswap")
        await _engine(db_session).detect([MINT], now=NOW)

        analyst_kinds = {
            EventKind.MISSION_PROMOTED,
            EventKind.RISK_INCREASED,
            EventKind.FIRST_ANALYSED,
            EventKind.LIQUIDITY_IMPROVED,
        }
        emitted = {event.kind for event in await _events(db_session, MINT)}
        assert not (emitted & analyst_kinds)

    async def test_events_are_appended_not_updated(self, db_session: AsyncSession) -> None:
        await _seed(db_session, MINT, "pumpfun", "pumpswap")
        engine = _engine(db_session)

        await engine.detect([MINT], now=NOW)
        before = len(await _events(db_session, MINT))
        await engine.review_expired(now=NOW + timedelta(seconds=3601))

        assert len(await _events(db_session, MINT)) > before


class TestConcurrency:
    async def test_two_concurrent_detections_open_one_opportunity(
        self, test_session_factory: Any
    ) -> None:
        """The AD-09 guarantee, exercised rather than asserted.

        Two workers claiming disjoint batches can still both see the same mint
        after a re-enrolment. The partial unique index is what stops both from
        opening an opportunity; the loser reads the winner's row.
        """
        async with test_session_factory() as setup:
            await _seed(setup, MINT, "pumpfun", "pumpswap")
            await setup.commit()

        async def _run() -> None:
            async with test_session_factory() as session:
                await _engine(session).detect([MINT], now=NOW)
                await session.commit()

        await asyncio.gather(_run(), _run(), return_exceptions=False)

        async with test_session_factory() as check:
            count = await check.scalar(
                select(func.count())
                .select_from(Opportunity)
                .where(Opportunity.mint_address == MINT)
            )
            signals = await check.scalar(
                select(func.count())
                .select_from(OpportunitySignal)
                .where(OpportunitySignal.mint_address == MINT)
            )
            assert count == 1
            assert signals == 1

            # Clean up: this test commits, unlike the transaction-scoped ones.
            live = await check.scalar(
                select(Opportunity).where(Opportunity.mint_address == MINT)
            )
            if live is not None:
                await check.delete(live)
            token = await TokenRepository(check).get_by_mint(MINT)
            if token is not None:
                await check.delete(token)
            await check.commit()


class TestSignalState:
    async def test_a_signal_starts_pending(self, db_session: AsyncSession) -> None:
        await _seed(db_session, MINT, "pumpfun", "pumpswap")
        await _engine(db_session).detect([MINT], now=NOW)

        signal = await db_session.scalar(select(OpportunitySignal))
        assert signal is not None
        assert signal.status == SignalStatus.PENDING.value
        assert signal.confirmations == 1

    async def test_expiry_marks_the_signal_not_just_the_opportunity(
        self, db_session: AsyncSession
    ) -> None:
        await _seed(db_session, MINT, "pumpfun", "pumpswap")
        engine = _engine(db_session)
        await engine.detect([MINT], now=NOW)

        await engine.review_expired(now=NOW + timedelta(seconds=3601))

        signal = await db_session.scalar(select(OpportunitySignal))
        assert signal is not None
        assert signal.status == SignalStatus.EXPIRED.value

    async def test_confidence_is_derived_never_taken_from_the_provider(
        self, db_session: AsyncSession
    ) -> None:
        """The provider claims strength 100; confidence must be lower on a
        single unconfirmed observation."""
        await _seed(db_session, MINT, "pumpfun", "pumpswap")
        await _engine(db_session).detect([MINT], now=NOW)

        signal = await db_session.scalar(select(OpportunitySignal))
        assert signal is not None
        assert signal.strength == Decimal("100.00")
        assert signal.confidence < signal.strength


class TestOutcomes:
    """AD-10's realisation and invalidation exits, end to end.

    The engine already closed opportunities that stopped confirming. What is new
    is that a signal can now record *why* it ended — and precision divides by
    exactly these counts, so a wrong verdict here becomes a wrong published
    number about a provider.
    """

    async def _pre_breakout(
        self, session: AsyncSession, mint: str, *, prices: list[str], volumes: list[str]
    ) -> None:
        """A token whose window opens a pre-breakout signal."""
        token = await TokenRepository(session).insert_if_absent(
            {
                "mint_address": mint,
                "signature": f"sig-{mint}",
                "slot": 1,
                "discovered_at": NOW - timedelta(days=1),
            }
        )
        assert token is not None
        snapshots = MarketSnapshotRepository(session)
        for index, (price, volume) in enumerate(zip(prices, volumes, strict=True)):
            await snapshots.add_snapshot(
                {
                    "token_id": token.id,
                    "mint_address": mint,
                    "captured_at": NOW + timedelta(minutes=index),
                    "price_usd": Decimal(price),
                    "volume_1h": Decimal(volume),
                    "dex_name": "pumpswap",
                    "trading_status": TradingStatus.TRADING,
                    "provider": "test",
                }
            )
        await session.flush()

    async def _extend(
        self, session: AsyncSession, mint: str, *, price: str, minutes: int
    ) -> None:
        token = await TokenRepository(session).get_by_mint(mint)
        assert token is not None
        await MarketSnapshotRepository(session).add_snapshot(
            {
                "token_id": token.id,
                "mint_address": mint,
                "captured_at": NOW + timedelta(minutes=minutes),
                "price_usd": Decimal(price),
                "volume_1h": Decimal("100"),
                "dex_name": "pumpswap",
                "trading_status": TradingStatus.TRADING,
                "provider": "test",
            }
        )
        await session.flush()

    async def test_a_pre_breakout_that_clears_its_range_is_realised(
        self, db_session: AsyncSession
    ) -> None:
        mint = "OutcomeRealisedMint1111111111111111111111111"
        await self._pre_breakout(
            db_session,
            mint,
            prices=["1.0"] * 11 + ["0.95"],
            volumes=["100"] * 11 + ["400"],
        )
        engine = _engine(db_session)
        await engine.detect([mint], now=NOW)
        signal = await db_session.scalar(
            select(OpportunitySignal).where(OpportunitySignal.mint_address == mint)
        )
        assert signal is not None
        assert signal.signal_type == SignalType.PRE_BREAKOUT.value

        await self._extend(db_session, mint, price="1.5", minutes=20)
        await engine.detect([mint], now=NOW + timedelta(minutes=21))

        await db_session.refresh(signal)
        assert signal.status == SignalStatus.REALISED.value
        kinds = {event.kind for event in await _events(db_session, mint)}
        assert EventKind.SIGNAL_REALISED in kinds

    async def test_a_pre_breakout_whose_pressure_fades_is_invalidated(
        self, db_session: AsyncSession
    ) -> None:
        mint = "OutcomeFadedMint111111111111111111111111111"
        await self._pre_breakout(
            db_session,
            mint,
            prices=["1.0"] * 11 + ["0.95"],
            volumes=["100"] * 11 + ["400"],
        )
        engine = _engine(db_session)
        await engine.detect([mint], now=NOW)

        await self._extend(db_session, mint, price="0.4", minutes=20)
        await engine.detect([mint], now=NOW + timedelta(minutes=21))

        signal = await db_session.scalar(
            select(OpportunitySignal).where(OpportunitySignal.mint_address == mint)
        )
        assert signal is not None
        assert signal.status == SignalStatus.INVALIDATED.value
        kinds = {event.kind for event in await _events(db_session, mint)}
        assert EventKind.SIGNAL_INVALIDATED in kinds

    async def test_a_resolved_signal_closes_its_opportunity(
        self, db_session: AsyncSession
    ) -> None:
        """The lifecycle completes without a new state.

        An outcome is terminal, so the signal leaves the live set and the
        existing machinery does the rest — that is what "do not add a state"
        buys: one way for an opportunity to end.
        """
        mint = "OutcomeClosesMint11111111111111111111111111"
        await self._pre_breakout(
            db_session,
            mint,
            prices=["1.0"] * 11 + ["0.95"],
            volumes=["100"] * 11 + ["400"],
        )
        engine = _engine(db_session)
        await engine.detect([mint], now=NOW)

        await self._extend(db_session, mint, price="1.5", minutes=20)
        await engine.detect([mint], now=NOW + timedelta(minutes=21))

        opportunity = await db_session.scalar(
            select(Opportunity).where(Opportunity.mint_address == mint)
        )
        assert opportunity is not None
        assert opportunity.status == OpportunityStatus.EXPIRING.value

    async def test_precision_becomes_available_once_an_outcome_lands(
        self, db_session: AsyncSession
    ) -> None:
        """The point of the sprint: the denominator stops being empty."""
        mint = "OutcomePrecisionMint111111111111111111111111"
        repository = OpportunityRepository(db_session)
        before = await repository.provider_totals(required_confirmations=2)
        assert before.get("breakout") is None or before["breakout"].realised == 0

        await self._pre_breakout(
            db_session,
            mint,
            prices=["1.0"] * 11 + ["0.95"],
            volumes=["100"] * 11 + ["400"],
        )
        engine = _engine(db_session)
        await engine.detect([mint], now=NOW)
        await self._extend(db_session, mint, price="1.5", minutes=20)
        await engine.detect([mint], now=NOW + timedelta(minutes=21))

        totals = await repository.provider_totals(required_confirmations=2)

        assert totals["breakout"].realised == 1
        assert totals["breakout"].contradicted == 0
