"""The scheduled lifecycle pass.

The engine's own transitions are covered in `test_opportunity_engine.py`. What
is asserted here is the thing that was missing entirely: that something in
production actually *calls* them, commits, and can be run twice without harm.

The async body is tested rather than the Celery-decorated wrapper — the wrapper
is one `asyncio.run` call and driving it from an async test would nest event
loops for no coverage gain, the same reasoning `test_scoring_tasks.py` records.

These commit real rows, because the task opens its own session. Everything
shares the `Sched` mint prefix and is removed by cascade.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import delete, select, update

from app.models.intelligence import EventKind, IntelligenceEvent
from app.models.market import TradingStatus
from app.models.opportunity import Opportunity, OpportunitySignal
from app.models.token import DiscoveredToken
from app.opportunities.models import OpportunityStatus
from app.opportunities.scheduler import _opportunity_review
from app.repositories.market import MarketSnapshotRepository
from app.repositories.token import TokenRepository

pytestmark = pytest.mark.integration

PREFIX = "Sched"


@pytest.fixture
async def sessions(test_session_factory: Any) -> AsyncIterator[Any]:
    yield test_session_factory
    async with test_session_factory() as session:
        await session.execute(
            delete(DiscoveredToken).where(DiscoveredToken.mint_address.like(f"{PREFIX}%"))
        )
        await session.commit()


@pytest.fixture(autouse=True)
def engine_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.opportunities.scheduler.settings.FEATURE_OPPORTUNITY_ENGINE_ENABLED", True
    )


def _policy(monkeypatch: pytest.MonkeyPatch, *, grace: int, archive: int) -> None:
    """Collapse the settling windows so successive passes advance the walk.

    The task takes no `now` — production never gets to choose one — so the
    policy moves instead, through `expiry_policy_from_settings`, which exists
    so the whole policy can be substituted. The TTL is deliberately left alone:
    a zero TTL would expire a signal in the same pass that created it, and the
    engine rightly refuses NEW -> EXPIRING.
    """
    monkeypatch.setattr("app.opportunities.engine.settings.OPPORTUNITY_GRACE_SECONDS", grace)
    monkeypatch.setattr(
        "app.opportunities.engine.settings.OPPORTUNITY_ARCHIVE_AFTER_SECONDS", archive
    )


async def _lapse(factory: Any, mint: str) -> None:
    """Backdate the signals so their TTL has run out.

    Moving stored timestamps into the past is what elapsed time does; the
    alternative — sleeping through a real TTL — would buy the same coverage at
    the cost of a slow suite.
    """
    async with factory() as session:
        opportunity = await session.scalar(
            select(Opportunity).where(Opportunity.mint_address == mint)
        )
        assert opportunity is not None
        past = datetime.now(UTC) - timedelta(hours=1)
        await session.execute(
            update(OpportunitySignal)
            .where(OpportunitySignal.opportunity_id == opportunity.id)
            .values(expires_at=past, last_confirmed_at=past, observed_at=past)
        )
        await session.commit()


async def _graduated(factory: Any, mint: str) -> None:
    """A token observed on the curve and then on the graduated venue."""
    base = datetime.now(UTC) - timedelta(minutes=10)
    async with factory() as session:
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
        for index, venue in enumerate(("pumpfun", "pumpswap")):
            await snapshots.add_snapshot(
                {
                    "token_id": token.id,
                    "mint_address": mint,
                    "captured_at": base + timedelta(minutes=index),
                    "price_usd": Decimal("0.001"),
                    "liquidity_usd": Decimal("5000"),
                    "dex_name": venue,
                    "trading_status": TradingStatus.TRADING,
                    "provider": "test",
                }
            )
        await session.commit()


async def _detect(factory: Any, mint: str) -> None:
    from app.opportunities.engine import OpportunityEngine

    async with factory() as session:
        await OpportunityEngine(session).detect([mint])
        await session.commit()


async def _row(factory: Any, mint: str) -> Opportunity:
    async with factory() as session:
        row = await session.scalar(
            select(Opportunity)
            .where(Opportunity.mint_address == mint)
            .order_by(Opportunity.generation.desc())
        )
        assert row is not None
        return row


async def _generation(factory: Any, mint: str, generation: int) -> Opportunity:
    async with factory() as session:
        row = await session.scalar(
            select(Opportunity).where(
                Opportunity.mint_address == mint,
                Opportunity.generation == generation,
            )
        )
        assert row is not None
        return row


async def _kinds(factory: Any, mint: str) -> set[EventKind]:
    async with factory() as session:
        rows = await session.scalars(
            select(IntelligenceEvent).where(IntelligenceEvent.mint_address == mint)
        )
        return {row.kind for row in rows}


class TestScheduledWalk:
    async def test_it_walks_active_to_expiring_to_closed_to_archived(
        self, sessions: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One transition per pass, in order, with nothing skipped.

        Each state is a claim the product makes — EXPIRING says "this stopped
        confirming", CLOSED writes the permanent record. A pass that jumped
        straight to ARCHIVED would lose both.
        """
        mint = f"{PREFIX}Walk"
        _policy(monkeypatch, grace=0, archive=0)
        await _graduated(sessions, mint)
        await _detect(sessions, mint)
        assert (await _row(sessions, mint)).status != OpportunityStatus.EXPIRING.value
        await _lapse(sessions, mint)

        await _opportunity_review()
        assert (await _row(sessions, mint)).status == OpportunityStatus.EXPIRING.value

        await _opportunity_review()
        closed = await _row(sessions, mint)
        assert closed.status == OpportunityStatus.CLOSED.value
        assert closed.closed_at is not None

        await _opportunity_review()
        archived = await _row(sessions, mint)
        assert archived.status == OpportunityStatus.ARCHIVED.value
        assert archived.archived_at is not None
        # The permanent record is what the Hall of Lessons reads.
        assert archived.detected_at == closed.detected_at
        assert EventKind.OPPORTUNITY_CLOSED in await _kinds(sessions, mint)

    async def test_the_engine_flag_gates_the_pass(
        self, sessions: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Off means reported as off, not a quiet no-op."""
        monkeypatch.setattr(
            "app.opportunities.scheduler.settings.FEATURE_OPPORTUNITY_ENGINE_ENABLED",
            False,
        )

        assert await _opportunity_review() == {"skipped": "engine_disabled"}


class TestRevival:
    async def test_detection_inside_grace_revives_in_place(
        self, sessions: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A signal that comes back is the same opportunity, not a new one.

        Minting a generation here would break every performance claim measured
        from `detected_at` — the same story told twice, counted twice.
        """
        mint = f"{PREFIX}Revive"
        _policy(monkeypatch, grace=3_600, archive=0)
        await _graduated(sessions, mint)
        await _detect(sessions, mint)
        opened = await _row(sessions, mint)
        await _lapse(sessions, mint)

        await _opportunity_review()
        assert (await _row(sessions, mint)).status == OpportunityStatus.EXPIRING.value

        await _detect(sessions, mint)

        revived = await _row(sessions, mint)
        assert revived.id == opened.id
        assert revived.generation == 1
        assert revived.status != OpportunityStatus.EXPIRING.value
        assert revived.closed_at is None
        assert revived.detected_at == opened.detected_at

    async def test_a_new_generation_opens_only_after_archival(
        self, sessions: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Closure is the boundary, and the closed record is not touched again.

        AD-09: "Reopening after close creates a new generation, never a
        resurrection". Closure — not archival — is what frees the token, because
        the live-status partial unique index is what holds "one card per token"
        and a CLOSED row has already left it. Archival is a settling period for
        the permanent record, not a lock on the next call.
        """
        mint = f"{PREFIX}Gen"
        _policy(monkeypatch, grace=0, archive=3_600)
        await _graduated(sessions, mint)
        await _detect(sessions, mint)
        first = await _row(sessions, mint)
        await _lapse(sessions, mint)

        await _opportunity_review()  # EXPIRING
        await _opportunity_review()  # CLOSED
        closed = await _row(sessions, mint)
        assert closed.status == OpportunityStatus.CLOSED.value

        await _detect(sessions, mint)

        latest = await _row(sessions, mint)
        assert latest.id != first.id
        assert latest.generation == 2

        # The first call stays exactly as it was recorded — two separate calls
        # remain separately measurable.
        settled = await _generation(sessions, mint, 1)
        assert settled.status == OpportunityStatus.CLOSED.value
        assert settled.detected_at == first.detected_at
        assert settled.closed_at == closed.closed_at

        # And archival still reaches it on its own schedule, without disturbing
        # the generation now live.
        monkeypatch.setattr(
            "app.opportunities.engine.settings.OPPORTUNITY_ARCHIVE_AFTER_SECONDS", 0
        )
        await _opportunity_review()

        assert (await _generation(sessions, mint, 1)).status == (
            OpportunityStatus.ARCHIVED.value
        )
        assert (await _generation(sessions, mint, 2)).status != (
            OpportunityStatus.ARCHIVED.value
        )


class TestIdempotence:
    async def test_a_duplicate_pass_changes_nothing(
        self, sessions: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Beat is a singleton, but a run can outlive its own interval.

        Every transition is a function of stored timestamps against `now`, so
        the second pass over the same rows must resolve the same states and
        write no second event. If it did not, the timeline would report a
        closure twice for one closing.
        """
        mint = f"{PREFIX}Twice"
        _policy(monkeypatch, grace=0, archive=0)
        await _graduated(sessions, mint)
        await _detect(sessions, mint)
        await _lapse(sessions, mint)

        # Run to the terminal state first: idempotence is a claim about a pass
        # that has nothing left to do, not about one mid-walk.
        await _opportunity_review()
        await _opportunity_review()
        await _opportunity_review()
        settled = await _row(sessions, mint)
        assert settled.status == OpportunityStatus.ARCHIVED.value
        events_before = len(await _events(sessions, mint))

        repeat = await _opportunity_review()

        after = await _row(sessions, mint)
        assert after.status == settled.status
        assert after.archived_at == settled.archived_at
        assert len(await _events(sessions, mint)) == events_before
        assert repeat["events_recorded"] == 0
        assert repeat["closed"] == 0
        assert repeat["archived"] == 0


async def _events(factory: Any, mint: str) -> list[IntelligenceEvent]:
    async with factory() as session:
        rows = await session.scalars(
            select(IntelligenceEvent).where(IntelligenceEvent.mint_address == mint)
        )
        return list(rows)
