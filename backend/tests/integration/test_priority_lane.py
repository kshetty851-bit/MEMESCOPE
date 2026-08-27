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
from app.models.market import (
    LANE_DISPLAY,
    LANE_NORMAL,
    LANE_NURSERY,
    EnrichmentStatus,
    TokenEnrichmentState,
)
from app.models.radar import RadarToken
from app.models.token import DiscoveredToken as TokenTable
from app.repositories.market import EnrichmentStateRepository
from app.repositories.token import TokenRepository
from app.services.market.priority import (
    NurseryMembership,
    apply_membership,
    refresh_nursery_lane,
    refresh_priority_lane,
    resolve_membership,
)
from app.workers import priority_tasks

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
        await _token_with_state(
            db_session, DISPLAYED, due_in_seconds=-1, priority=LANE_DISPLAY
        )
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
        await _token_with_state(
            db_session, DISPLAYED, due_in_seconds=600, priority=LANE_DISPLAY
        )
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

        assert state.priority == LANE_DISPLAY
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
            db_session, DISPLAYED, due_in_seconds=21_600, priority=LANE_DISPLAY
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
        await _token_with_state(
            db_session, DISPLAYED, due_in_seconds=5, priority=LANE_DISPLAY
        )
        await db_session.commit()

        promoted, demoted = await apply_membership(db_session, {DISPLAYED}, now=NOW)

        assert (promoted, demoted) == (0, 0)


class TestMembershipIsDerivedNotAccumulated:
    async def test_a_token_that_leaves_the_visible_set_leaves_the_lane(
        self, db_session: AsyncSession
    ) -> None:
        """Otherwise the lane grows monotonically and becomes the backlog it
        was built to escape."""
        state = await _token_with_state(
            db_session, DISPLAYED, due_in_seconds=5, priority=LANE_DISPLAY
        )
        await db_session.commit()

        _, demoted = await apply_membership(db_session, set(), now=NOW)
        await db_session.commit()
        await db_session.refresh(state)

        assert demoted == 1
        assert state.priority == LANE_NORMAL

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


async def _fresh_token_with_state(
    session: AsyncSession,
    mint: str,
    *,
    age_minutes: float,
    priority: int = LANE_NORMAL,
    due_in_seconds: int = 3600,
) -> TokenEnrichmentState:
    token = await TokenRepository(session).insert_if_absent(
        {
            "mint_address": mint,
            "signature": f"sig-{mint}",
            "slot": 1,
            "discovered_at": NOW - timedelta(minutes=age_minutes),
            "block_time": NOW - timedelta(minutes=age_minutes),
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


class TestTheNursery:
    """The fresh-token nursery: discovery itself qualifies a token for
    observation priority, which is what breaks the circularity of needing
    observations to become interesting and needing to be interesting to be
    observed."""

    async def test_a_fresh_token_is_admitted_and_pulled_due(
        self, db_session: AsyncSession
    ) -> None:
        state = await _fresh_token_with_state(
            db_session, "NurseryFresh" + "1" * 31, age_minutes=2
        )
        await db_session.commit()

        outcome = await refresh_nursery_lane(db_session, now=NOW)
        await db_session.commit()
        await db_session.refresh(state)

        assert outcome.promoted == 1
        assert state.priority == LANE_NURSERY
        assert state.next_refresh_at <= NOW

    async def test_the_nursery_claims_before_the_backlog_but_after_the_display_lane(
        self, db_session: AsyncSession
    ) -> None:
        """Open positions and the visible board always outrank speculation."""
        await _token_with_state(db_session, BACKLOG, due_in_seconds=-7200)
        await _token_with_state(
            db_session, DISPLAYED, due_in_seconds=-1, priority=LANE_DISPLAY
        )
        await _fresh_token_with_state(
            db_session,
            "NurseryClaims" + "1" * 30,
            age_minutes=2,
            priority=LANE_NURSERY,
            due_in_seconds=-30,
        )
        await db_session.commit()

        repository = EnrichmentStateRepository(db_session)
        first = await repository.claim_due(now=NOW, limit=1)
        second = await repository.claim_due(now=NOW, limit=1)

        assert [row.mint_address for row in first] == [DISPLAYED]
        assert [row.mint_address for row in second] == ["NurseryClaims" + "1" * 30]

    async def test_a_token_past_the_window_is_evicted(self, db_session: AsyncSession) -> None:
        """Weak tokens return to the age-tier cadence; the lane never
        accumulates."""
        state = await _fresh_token_with_state(
            db_session,
            "NurseryAged" + "1" * 32,
            age_minutes=settings.ENRICHMENT_TIER_FRESH_MAX_MINUTES + 5,
            priority=LANE_NURSERY,
        )
        await db_session.commit()

        outcome = await refresh_nursery_lane(db_session, now=NOW)
        await db_session.commit()
        await db_session.refresh(state)

        assert outcome.evicted_aged == 1
        assert state.priority == LANE_NORMAL

    async def test_the_cap_trims_oldest_first_and_is_reported(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """20k launches must never become 20k lane members: a storm costs the
        oldest fresh tokens their tail minutes, never the newest its first
        look, and the trim is counted rather than silent."""
        monkeypatch.setattr(settings, "ENRICHMENT_NURSERY_MAX_TOKENS", 2)
        states = [
            await _fresh_token_with_state(
                db_session,
                f"NurseryCap{index:033d}",
                age_minutes=index + 1,
                priority=LANE_NURSERY,
            )
            for index in range(4)
        ]
        await db_session.commit()

        outcome = await refresh_nursery_lane(db_session, now=NOW)
        await db_session.commit()
        for state in states:
            await db_session.refresh(state)

        assert outcome.evicted_capacity == 2
        assert outcome.capped is True
        assert [state.priority for state in states] == [
            LANE_NURSERY,
            LANE_NURSERY,
            LANE_NORMAL,
            LANE_NORMAL,
        ]

    async def test_a_zero_capacity_disables_the_lane_and_drains_it(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Turning the lane off must evict whoever is already inside. Skipping
        the pass would strand them above the entire normal population
        indefinitely, long past their window."""
        monkeypatch.setattr(settings, "ENRICHMENT_NURSERY_MAX_TOKENS", 0)
        state = await _fresh_token_with_state(
            db_session, "NurseryOff" + "1" * 33, age_minutes=2, priority=LANE_NURSERY
        )
        await db_session.commit()

        outcome = await refresh_nursery_lane(db_session, now=NOW)
        await db_session.commit()
        await db_session.refresh(state)

        assert outcome.members == 0
        assert outcome.promoted == 0
        assert outcome.evicted_capacity == 1
        assert state.priority == LANE_NORMAL

    async def test_a_dead_lettered_fresh_token_is_not_admitted(
        self, db_session: AsyncSession
    ) -> None:
        """Readmission is the requeue beat's job; the nursery must not undo a
        quarantine."""
        state = await _fresh_token_with_state(
            db_session, "NurseryDead" + "1" * 32, age_minutes=2
        )
        state.status = EnrichmentStatus.DEAD_LETTER
        await db_session.commit()

        outcome = await refresh_nursery_lane(db_session, now=NOW)
        await db_session.commit()
        await db_session.refresh(state)

        assert outcome.promoted == 0
        assert state.priority == LANE_NORMAL

    async def test_maintenance_runs_even_with_the_display_lane_flag_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Admission and enforcement must never sit behind different switches.

        `register_token` admits on `ENRICHMENT_NURSERY_MAX_TOKENS` alone, and
        the nursery pass is the only code that takes a token back out. Gating
        that pass on `FEATURE_PRIORITY_ENRICHMENT_ENABLED` — the display lane's
        incident lever — meant flipping the flag off left admission running
        with eviction stopped, growing the lane without bound and never
        expiring it. The pass must also run at capacity zero, because the
        capacity trim is how the lane is drained.
        """
        calls: list[str] = []

        async def _recording_nursery(session: object, *, now: object) -> NurseryMembership:
            calls.append("nursery")
            return NurseryMembership(
                members=0, promoted=0, evicted_aged=0, evicted_capacity=0, capped=False
            )

        monkeypatch.setattr(priority_tasks, "refresh_nursery_lane", _recording_nursery)

        for flag, capacity in ((False, 600), (True, 0), (False, 0)):
            calls.clear()
            monkeypatch.setattr(settings, "FEATURE_PRIORITY_ENRICHMENT_ENABLED", flag)
            monkeypatch.setattr(settings, "ENRICHMENT_NURSERY_MAX_TOKENS", capacity)

            result = await priority_tasks._refresh()

            assert calls == ["nursery"], f"flag={flag} capacity={capacity}"
            assert "nursery" in result


class TestTheLabsBookIsProtected:
    """The Lab holds the platform's live book. Its tokens must keep getting
    priced, or its positions cannot be marked — or sold.

    Regression for HQ INC-056: the lane queried `paper_positions` only, so when
    the Paper wallet was retired it reported `paper: 0` and the Lab's holdings
    inherited no protection. 61 of 108 open positions went unmarkable.
    """

    @staticmethod
    async def _lab_position(session: AsyncSession, mint: str) -> None:
        """Seed through the Lab's own activation, so the row shape stays the
        Lab's problem rather than this test's."""
        from decimal import Decimal

        from app.lab.service import LabService
        from app.models.lab import LabDecision, LabPosition, LabStrategy

        await LabService(session).activate(valid_from=NOW - timedelta(days=1))
        row = (await session.execute(select(LabStrategy).limit(1))).scalars().one()
        token_id = await session.scalar(
            select(TokenTable.id).where(TokenTable.mint_address == mint)
        )
        decision = LabDecision(
            strategy_row_id=row.id, strategy_id=row.strategy_id,
            mint_address=mint, token_id=token_id,
            checkpoint_at=NOW, checkpoint_minutes=30, decided_at=NOW,
            eligible=True, features={}, snapshot_ids={},
        )
        session.add(decision)
        await session.flush()
        session.add(LabPosition(
            decision_id=decision.id,
            strategy_row_id=row.id, strategy_id=row.strategy_id,
            mint_address=mint, token_id=token_id, opened_at=NOW,
            entry_price=Decimal("1"), size_usd=Decimal("5"),
            quantity=Decimal("5"), quantity_remaining=Decimal("5"),
            banked_proceeds_usd=Decimal(0), status="open", entry_source="model",
            peak_exec_multiple=Decimal(1),
        ))
        await session.flush()

    async def test_an_open_lab_holding_joins_the_lane(
        self, db_session: AsyncSession
    ) -> None:
        mint = "LabHeld" + "1" * 30
        await _token_with_state(db_session, mint, due_in_seconds=9_000)
        await self._lab_position(db_session, mint)
        await db_session.flush()

        members, membership = await resolve_membership(db_session)

        assert mint in members, "an open Lab position must be kept priced"
        assert membership.lab >= 1

    async def test_a_token_the_lab_does_not_hold_is_not_pulled_in(
        self, db_session: AsyncSession
    ) -> None:
        """The lane stays a bounded, derived set — not everything ever seen."""
        mint = "LabAbsent" + "1" * 28
        await _token_with_state(db_session, mint, due_in_seconds=9_000)
        await db_session.flush()

        members, _ = await resolve_membership(db_session)
        assert mint not in members
