"""Dead-lettering is a quarantine, not a grave.

`requeue_dead_letters` existed on the repository from the beginning, documented
as an operator action, and **nothing in the codebase ever called it**. So a
token removed from the queue by one bad minute was gone until somebody noticed
and intervened by hand — and on 2026-08-05 nobody did, so 163 of the 200 tokens
in the priority enrichment lane stayed parked long after the provider recovered,
including ten of the paper wallet's twelve holdings.

The root cause is fixed in `MarketEnrichmentService._defer`. These tests cover
the second half: whatever parks a token in future, from any cause, must heal.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.market import EnrichmentStatus
from app.repositories.market import EnrichmentStateRepository
from app.repositories.token import TokenRepository

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC).replace(microsecond=0)


async def _dead_lettered(session: AsyncSession, mint: str, *, idle_minutes: int) -> object:
    token = await TokenRepository(session).insert_if_absent(
        {
            "mint_address": mint,
            "signature": f"sig-{mint}",
            "slot": 1,
            "discovered_at": NOW - timedelta(days=1),
            "block_time": NOW - timedelta(days=1),
        }
    )
    assert token is not None
    repository = EnrichmentStateRepository(session)
    state = await repository.ensure_state(
        token_id=token.id,  # type: ignore[attr-defined]
        mint_address=mint,
        next_refresh_at=NOW,
    )
    assert state is not None
    state.status = EnrichmentStatus.DEAD_LETTER
    state.consecutive_failures = 10
    state.last_error = "provider exploded"
    state.last_attempt_at = NOW - timedelta(minutes=idle_minutes)
    await session.flush()
    return state


class TestReadmission:
    async def test_a_token_that_served_its_quarantine_comes_back(
        self, db_session: AsyncSession
    ) -> None:
        state = await _dead_lettered(db_session, "MintRevive", idle_minutes=120)

        requeued = await EnrichmentStateRepository(db_session).requeue_dead_letters(
            now=NOW, idle_for=timedelta(minutes=60)
        )

        assert requeued == 1
        assert state.status is EnrichmentStatus.ACTIVE  # type: ignore[attr-defined]
        # The failure budget resets too, or the token would be parked again by
        # the very next error rather than getting a genuine second chance.
        assert state.consecutive_failures == 0  # type: ignore[attr-defined]
        assert state.last_error is None  # type: ignore[attr-defined]

    async def test_a_readmitted_token_is_claimable_again(
        self, db_session: AsyncSession
    ) -> None:
        """The whole point. Readmission that did not restore it to the queue
        would be a status change and nothing more."""
        await _dead_lettered(db_session, "MintClaimable", idle_minutes=120)
        repository = EnrichmentStateRepository(db_session)

        assert await repository.claim_due(now=NOW, limit=10) == []

        await repository.requeue_dead_letters(now=NOW, idle_for=timedelta(minutes=60))
        claimed = await repository.claim_due(now=NOW, limit=10)

        assert [state.mint_address for state in claimed] == ["MintClaimable"]

    async def test_a_freshly_parked_token_waits(self, db_session: AsyncSession) -> None:
        """Without the idle gate this is a retry loop: a genuinely broken mint
        would be readmitted on every pass and cost a call every five minutes."""
        state = await _dead_lettered(db_session, "MintTooSoon", idle_minutes=5)

        requeued = await EnrichmentStateRepository(db_session).requeue_dead_letters(
            now=NOW, idle_for=timedelta(minutes=60)
        )

        assert requeued == 0
        assert state.status is EnrichmentStatus.DEAD_LETTER  # type: ignore[attr-defined]

    async def test_the_pass_is_bounded_so_a_backlog_drains_gradually(
        self, db_session: AsyncSession
    ) -> None:
        """A thousand tokens arriving at once on a provider that may still be
        unwell is how the outage repeats itself."""
        for index in range(6):
            await _dead_lettered(db_session, f"MintBulk{index}", idle_minutes=120)

        requeued = await EnrichmentStateRepository(db_session).requeue_dead_letters(
            now=NOW, limit=4, idle_for=timedelta(minutes=60)
        )

        assert requeued == 4

    async def test_the_longest_parked_are_readmitted_first(
        self, db_session: AsyncSession
    ) -> None:
        """Ordering makes the bounded pass fair. Heap order would let the same
        rows come back every cycle and starve the tail — the failure that
        livelocked the score sweep."""
        await _dead_lettered(db_session, "MintRecent", idle_minutes=61)
        await _dead_lettered(db_session, "MintAncient", idle_minutes=600)

        await EnrichmentStateRepository(db_session).requeue_dead_letters(
            now=NOW, limit=1, idle_for=timedelta(minutes=60)
        )
        claimed = await EnrichmentStateRepository(db_session).claim_due(now=NOW, limit=10)

        assert [state.mint_address for state in claimed] == ["MintAncient"]


class TestTheBeat:
    async def test_it_is_registered_so_recovery_actually_runs(self) -> None:
        """The defect was never the method — it was that nothing called it.

        This asserts the thing that was missing, which is why it is a test
        about registration rather than about behaviour.
        """
        from app.workers.celery_app import celery_app

        entry = celery_app.conf.beat_schedule["enrichment-requeue-dead-letters"]

        assert entry["task"] == "app.workers.enrichment_tasks.requeue_dead_letters"
        assert "app.workers.enrichment_tasks" in celery_app.conf.include

    async def test_it_reports_zero_rather_than_staying_silent(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A recovery beat that only speaks when it acts is indistinguishable
        from one that stopped running — and "nothing refreshed for an hour" is
        precisely the failure it exists to catch."""
        from app.workers import enrichment_tasks

        monkeypatch.setattr(settings, "ENRICHMENT_DEAD_LETTER_REQUEUE_LIMIT", 10)
        result = await enrichment_tasks._requeue()

        assert "requeued" in result
