"""The priority enrichment lane.

Sprint 28. The queue reached 36,154 active tokens and the claim query ordered by
due time alone, so a Radar token asking for a fifteen-second refresh sorted
behind 36,000 rows that were hours overdue — measured p95 gap 106 minutes, with
three of the visible Top 10 showing prices nearly three hours old.

What is asserted here is that the lane is a **lane and not a second queue**: one
column, one ORDER BY term, the same table and the same worker.

The clamp test exists because the first implementation got this wrong. Sorting
ahead of the backlog is not enough on its own — the stale tokens are stale
*because* they sit on a six-hour interval, so promotion that leaves the due time
alone keeps them stale for six more hours. Measured with sort-order-only
promotion, the stale count fell just 84 -> 74 over four minutes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.market import EnrichmentStatus, TokenEnrichmentState
from app.models.radar import RadarToken
from app.models.token import DiscoveredToken as TokenTable
from app.repositories.market import EnrichmentStateRepository
from app.repositories.token import TokenRepository
from app.services.market.priority import apply_membership, refresh_priority_lane

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC).replace(microsecond=0)


async def _token_with_state(
    session: AsyncSession, mint: str, *, due_in_seconds: int, priority: int = 0
) -> TokenEnrichmentState:
    token = await TokenRepository(session).insert_if_absent(
        {
            "mint_address": mint,
            "signature": f"sig-{mint}",
            "slot": 1,
            "discovered_at": NOW - timedelta(days=7),
            "block_time": NOW - timedelta(days=7),
            "symbol": mint[:6],
        }
    )
    assert token is not None
    state = TokenEnrichmentState(
        token_id=token.id,
        mint_address=mint,
        status=EnrichmentStatus.ACTIVE,
        next_refresh_at=NOW + timedelta(seconds=due_in_seconds),
        priority=priority,
    )
    session.add(state)
    await session.flush()
    return state


async def _radar_entry(session: AsyncSession, mint: str, *, score: int) -> None:
    token_id = await session.scalar(
        select(TokenTable.id).where(TokenTable.mint_address == mint)
    )
    session.add(
        RadarToken(
            token_id=token_id,
            mint_address=mint,
            first_detected_at=NOW - timedelta(days=1),
            first_market_cap=None,
            first_opportunity_score=score,
            first_confidence=40,
            detection_reason=["probe"],
            category="early_momentum",
            current_opportunity_score=score,
            current_confidence=40,
            current_category="early_momentum",
            is_active=True,
            model_version="v1",
        )
    )
    await session.flush()


BACKLOG = "PriorityBacklogMint11111111111111111111111"
DISPLAYED = "PriorityDisplayedMint2222222222222222222222"


class TestTheLaneJumpsTheBacklog:
    async def test_a_priority_token_is_claimed_before_an_older_due_one(
        self, db_session: AsyncSession
    ) -> None:
        """The whole point. Ordering by due time alone is what produced a
        106-minute p95 for tokens the product was displaying."""
        await _token_with_state(db_session, BACKLOG, due_in_seconds=-7200)
        await _token_with_state(db_session, DISPLAYED, due_in_seconds=-1, priority=1)
        await db_session.commit()

        claimed = await EnrichmentStateRepository(db_session).claim_due(now=NOW, limit=1)

        assert [row.mint_address for row in claimed] == [DISPLAYED]

    async def test_within_a_lane_the_oldest_due_still_wins(
        self, db_session: AsyncSession
    ) -> None:
        """The ordinary population must not starve its own tail."""
        await _token_with_state(db_session, BACKLOG, due_in_seconds=-7200)
        await _token_with_state(db_session, DISPLAYED, due_in_seconds=-60)
        await db_session.commit()

        claimed = await EnrichmentStateRepository(db_session).claim_due(now=NOW, limit=1)

        assert [row.mint_address for row in claimed] == [BACKLOG]

    async def test_a_token_not_yet_due_is_never_claimed_by_lane_alone(
        self, db_session: AsyncSession
    ) -> None:
        """Priority reorders; it does not bypass the due-time predicate."""
        await _token_with_state(db_session, DISPLAYED, due_in_seconds=600, priority=1)
        await db_session.commit()

        claimed = await EnrichmentStateRepository(db_session).claim_due(now=NOW, limit=10)

        assert claimed == []


class TestPromotionClamp:
    async def test_promotion_pulls_a_far_future_refresh_forward(
        self, db_session: AsyncSession
    ) -> None:
        """A token on the six-hour OLD interval is exactly the stale one the
        lane exists for. Sorting it first while leaving it six hours from due
        would change nothing."""
        state = await _token_with_state(db_session, DISPLAYED, due_in_seconds=21_600)
        await db_session.commit()

        await apply_membership(db_session, {DISPLAYED}, now=NOW)
        await db_session.commit()
        await db_session.refresh(state)

        assert state.priority == 1
        limit = NOW + timedelta(seconds=settings.ENRICHMENT_PRIORITY_INTERVAL_SECONDS)
        assert state.next_refresh_at <= limit

    async def test_it_clamps_rather_than_assigns(self, db_session: AsyncSession) -> None:
        """A token already due sooner keeps its earlier time — promotion can
        only ever bring a refresh forward, never push one back."""
        state = await _token_with_state(db_session, DISPLAYED, due_in_seconds=-300)
        earlier = state.next_refresh_at
        await db_session.commit()

        await apply_membership(db_session, {DISPLAYED}, now=NOW)
        await db_session.commit()
        await db_session.refresh(state)

        assert state.next_refresh_at == earlier

    async def test_a_member_whose_due_time_drifted_is_re_clamped(
        self, db_session: AsyncSession
    ) -> None:
        """Found by measurement: re-running the beat promoted only 3 of 200
        because the rest were already `priority = 1` and kept six-hour due
        times forever."""
        state = await _token_with_state(
            db_session, DISPLAYED, due_in_seconds=21_600, priority=1
        )
        await db_session.commit()

        promoted, _ = await apply_membership(db_session, {DISPLAYED}, now=NOW)
        await db_session.commit()
        await db_session.refresh(state)

        assert promoted == 1
        assert state.next_refresh_at <= NOW + timedelta(
            seconds=settings.ENRICHMENT_PRIORITY_INTERVAL_SECONDS
        )

    async def test_an_unchanged_member_is_not_rewritten(
        self, db_session: AsyncSession
    ) -> None:
        """The predicate keeps a steady cycle from producing dead tuples."""
        await _token_with_state(db_session, DISPLAYED, due_in_seconds=5, priority=1)
        await db_session.commit()

        promoted, demoted = await apply_membership(db_session, {DISPLAYED}, now=NOW)

        assert (promoted, demoted) == (0, 0)


class TestMembershipIsDerivedNotAccumulated:
    async def test_a_token_that_leaves_the_visible_set_leaves_the_lane(
        self, db_session: AsyncSession
    ) -> None:
        """Otherwise the lane grows monotonically and becomes the backlog it
        was built to escape."""
        state = await _token_with_state(db_session, DISPLAYED, due_in_seconds=5, priority=1)
        await db_session.commit()

        _, demoted = await apply_membership(db_session, set(), now=NOW)
        await db_session.commit()
        await db_session.refresh(state)

        assert demoted == 1
        assert state.priority == 0

    async def test_the_lane_is_capped(self, db_session: AsyncSession) -> None:
        """A bug that marks everything priority must not turn the lane back
        into the backlog."""
        for index in range(3):
            mint = f"PriorityCap{index:031d}"
            await _token_with_state(db_session, mint, due_in_seconds=5)
            await _radar_entry(db_session, mint, score=90 - index)
        await db_session.commit()

        membership = await refresh_priority_lane(db_session, now=NOW)

        assert membership.total <= settings.ENRICHMENT_PRIORITY_MAX_TOKENS
        assert membership.radar == 3
