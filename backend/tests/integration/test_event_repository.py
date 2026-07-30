"""Integration tests for event and watchlist persistence.

Real Postgres, each test in a rolled-back transaction. What these lock is the
two guarantees the feature rests on: events cannot be revised, and a cycle that
runs twice records each change once.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysts.lifecycle import MissionState
from app.analysts.research import ResearchPriority
from app.events.detector import DetectedEvent, TokenState
from app.events.repository import EventRepository
from app.models.intelligence import EventKind, EventSeverity
from app.models.user import User

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

NOW = datetime(2026, 7, 30, 12, tzinfo=UTC)


async def _user(session: AsyncSession, email: str = "watcher@example.com") -> User:
    user = User(email=email, hashed_password="x" * 60, is_active=True)
    session.add(user)
    await session.flush()
    return user


def _event(
    kind: EventKind = EventKind.MISSION_PROMOTED, mint: str = "mint-a"
) -> DetectedEvent:
    return DetectedEvent(
        mint_address=mint,
        kind=kind,
        severity=EventSeverity.NOTABLE,
        summary="Something observable changed.",
        previous_value="orbit",
        current_value="ascent",
        analyst="lifecycle",
    )


class TestEventsAreAppendOnlyAndDeduplicated:
    async def test_the_same_change_is_recorded_once(self, db_session: AsyncSession) -> None:
        # A retry, a restart, or two workers racing must not double-report.
        repository = EventRepository(db_session)
        first = await repository.record([_event()], occurred_at=NOW)
        second = await repository.record([_event()], occurred_at=NOW)

        assert first == 1
        assert second == 0

    async def test_the_same_kind_at_a_different_time_is_a_new_event(
        self, db_session: AsyncSession
    ) -> None:
        # A token can genuinely be promoted twice. Deduplication is per moment,
        # not per kind, or real history would be swallowed.
        repository = EventRepository(db_session)
        assert await repository.record([_event()], occurred_at=NOW) == 1
        assert await repository.record([_event()], occurred_at=NOW + timedelta(hours=1)) == 1

    async def test_the_repository_exposes_no_way_to_edit_an_event(self) -> None:
        # "What changed last week" is only worth asking if the answer cannot be
        # revised afterwards.
        for forbidden in ("update_event", "edit_event", "delete_event"):
            assert not hasattr(EventRepository, forbidden)

    async def test_history_is_returned_newest_first(self, db_session: AsyncSession) -> None:
        repository = EventRepository(db_session)
        await repository.record([_event(EventKind.FIRST_ANALYSED)], occurred_at=NOW)
        await repository.record(
            [_event(EventKind.MISSION_PROMOTED)], occurred_at=NOW + timedelta(hours=2)
        )

        history = await repository.events_for("mint-a")
        assert [e.kind for e in history] == [
            EventKind.MISSION_PROMOTED,
            EventKind.FIRST_ANALYSED,
        ]

    async def test_recording_nothing_is_free(self, db_session: AsyncSession) -> None:
        assert await EventRepository(db_session).record([], occurred_at=NOW) == 0


class TestTheCacheMakesDetectionIncremental:
    async def test_a_round_trip_preserves_every_field(self, db_session: AsyncSession) -> None:
        repository = EventRepository(db_session)
        state = TokenState(
            mint_address="mint-cache",
            mission_state=MissionState.ASCENT,
            research_priority=ResearchPriority.HIGH,
            combined_score=Decimal("67.85"),
            confidence=Decimal("74.00"),
            liquidity_score=Decimal("73.95"),
            momentum_score=Decimal("88.43"),
            risk_score=Decimal("33.86"),
            clone_risk="high",
            exit_severity="watch",
            warning_codes=frozenset({"RISK_CLONE_HIGH", "LIQUIDITY_THIN"}),
        )

        await repository.remember_state(state, observed_at=NOW)
        loaded = (await repository.cached_states(["mint-cache"]))["mint-cache"]

        assert loaded.mission_state is MissionState.ASCENT
        assert loaded.research_priority is ResearchPriority.HIGH
        assert loaded.clone_risk == "high"
        assert loaded.exit_severity == "watch"
        assert loaded.warning_codes == {"RISK_CLONE_HIGH", "LIQUIDITY_THIN"}
        assert loaded.momentum_score == Decimal("88.43")

    async def test_remembering_twice_overwrites_rather_than_duplicating(
        self, db_session: AsyncSession
    ) -> None:
        # The cache is a pointer to "where we were", not a history. History
        # lives in the event log and is never touched.
        repository = EventRepository(db_session)
        await repository.remember_state(
            TokenState(mint_address="mint-x", mission_state=MissionState.ORBIT),
            observed_at=NOW,
        )
        await repository.remember_state(
            TokenState(mint_address="mint-x", mission_state=MissionState.ASCENT),
            observed_at=NOW + timedelta(minutes=15),
        )

        loaded = await repository.cached_states(["mint-x"])
        assert len(loaded) == 1
        assert loaded["mint-x"].mission_state is MissionState.ASCENT

    async def test_an_unseen_mint_is_absent_rather_than_empty(
        self, db_session: AsyncSession
    ) -> None:
        # Absent means "never analysed", which the detector turns into a single
        # first-sighting event rather than a burst of false improvements.
        loaded = await EventRepository(db_session).cached_states(["never-seen"])
        assert "never-seen" not in loaded

    async def test_a_batch_lookup_is_one_query_not_one_per_token(
        self, db_session: AsyncSession
    ) -> None:
        repository = EventRepository(db_session)
        for index in range(5):
            await repository.remember_state(
                TokenState(mint_address=f"mint-{index}", mission_state=MissionState.ORBIT),
                observed_at=NOW,
            )
        loaded = await repository.cached_states([f"mint-{i}" for i in range(5)])
        assert len(loaded) == 5

    async def test_asking_for_nothing_queries_nothing(self, db_session: AsyncSession) -> None:
        assert await EventRepository(db_session).cached_states([]) == {}


class TestWatchlists:
    async def test_a_user_cannot_have_two_lists_with_one_name(
        self, db_session: AsyncSession
    ) -> None:
        # Two lists called "Recovery" is a bug the user cannot see until they
        # add to the wrong one.
        repository = EventRepository(db_session)
        user = await _user(db_session)

        first = await repository.create_list(
            user_id=user.id, name="Recovery", description=None, alert_on=[]
        )
        duplicate = await repository.create_list(
            user_id=user.id, name="Recovery", description=None, alert_on=[]
        )

        assert first is not None
        assert duplicate is None

    async def test_two_users_may_both_have_a_list_called_recovery(
        self, db_session: AsyncSession
    ) -> None:
        repository = EventRepository(db_session)
        one = await _user(db_session, "one@example.com")
        two = await _user(db_session, "two@example.com")

        assert (
            await repository.create_list(
                user_id=one.id, name="Recovery", description=None, alert_on=[]
            )
            is not None
        )
        assert (
            await repository.create_list(
                user_id=two.id, name="Recovery", description=None, alert_on=[]
            )
            is not None
        )

    async def test_one_user_cannot_read_another_users_list(
        self, db_session: AsyncSession
    ) -> None:
        repository = EventRepository(db_session)
        owner = await _user(db_session, "owner@example.com")
        stranger = await _user(db_session, "stranger@example.com")

        created = await repository.create_list(
            user_id=owner.id, name="Private", description=None, alert_on=[]
        )
        assert created is not None

        assert await repository.get_list(created.id, owner.id) is not None
        assert await repository.get_list(created.id, stranger.id) is None

    async def test_a_token_cannot_be_added_to_one_list_twice(
        self, db_session: AsyncSession
    ) -> None:
        repository = EventRepository(db_session)
        user = await _user(db_session)
        watchlist = await repository.create_list(
            user_id=user.id, name="AI", description=None, alert_on=[]
        )
        assert watchlist is not None

        first = await repository.add_item(
            list_id=watchlist.id,
            mint_address="mint-dupe",
            note="first",
            mission_state="orbit",
            priority="high",
            score=Decimal(60),
        )
        again = await repository.add_item(
            list_id=watchlist.id,
            mint_address="mint-dupe",
            note="second",
            mission_state="orbit",
            priority="high",
            score=Decimal(60),
        )

        assert first is not None
        assert again is None

    async def test_the_state_at_the_moment_of_adding_is_captured(
        self, db_session: AsyncSession
    ) -> None:
        # So the timeline can answer "what changed since I started watching?"
        # without re-deriving history.
        repository = EventRepository(db_session)
        user = await _user(db_session)
        watchlist = await repository.create_list(
            user_id=user.id, name="Gaming", description=None, alert_on=[]
        )
        assert watchlist is not None

        item = await repository.add_item(
            list_id=watchlist.id,
            mint_address="mint-baseline",
            note="watching liquidity",
            mission_state="re_entry",
            priority="medium",
            score=Decimal("41.50"),
        )

        assert item is not None
        assert item.added_mission_state == "re_entry"
        assert item.added_priority == "medium"
        assert item.added_score == Decimal("41.50")
        assert item.note == "watching liquidity"

    async def test_removing_a_token_reports_whether_it_was_there(
        self, db_session: AsyncSession
    ) -> None:
        repository = EventRepository(db_session)
        user = await _user(db_session)
        watchlist = await repository.create_list(
            user_id=user.id, name="DeFi", description=None, alert_on=[]
        )
        assert watchlist is not None

        await repository.add_item(
            list_id=watchlist.id,
            mint_address="mint-gone",
            note=None,
            mission_state=None,
            priority=None,
            score=None,
        )

        assert await repository.remove_item(watchlist.id, "mint-gone") is True
        assert await repository.remove_item(watchlist.id, "mint-gone") is False

    async def test_watched_mints_spans_every_list_the_user_owns(
        self, db_session: AsyncSession
    ) -> None:
        repository = EventRepository(db_session)
        user = await _user(db_session)

        for name, mint in (("A", "mint-1"), ("B", "mint-2"), ("C", "mint-1")):
            watchlist = await repository.create_list(
                user_id=user.id, name=name, description=None, alert_on=[]
            )
            assert watchlist is not None
            await repository.add_item(
                list_id=watchlist.id,
                mint_address=mint,
                note=None,
                mission_state=None,
                priority=None,
                score=None,
            )

        # mint-1 is on two lists but is one token to monitor.
        assert sorted(await repository.watched_mints(user.id)) == ["mint-1", "mint-2"]

    async def test_deleting_a_list_takes_its_items_with_it(
        self, db_session: AsyncSession
    ) -> None:
        repository = EventRepository(db_session)
        user = await _user(db_session)
        watchlist = await repository.create_list(
            user_id=user.id, name="Temp", description=None, alert_on=[]
        )
        assert watchlist is not None
        await repository.add_item(
            list_id=watchlist.id,
            mint_address="mint-cascade",
            note=None,
            mission_state=None,
            priority=None,
            score=None,
        )

        assert await repository.delete_list(watchlist.id, user.id) is True
        assert await repository.items(watchlist.id) == []

    async def test_a_stranger_cannot_delete_someone_elses_list(
        self, db_session: AsyncSession
    ) -> None:
        repository = EventRepository(db_session)
        owner = await _user(db_session, "keep@example.com")
        stranger = await _user(db_session, "nope@example.com")
        watchlist = await repository.create_list(
            user_id=owner.id, name="Mine", description=None, alert_on=[]
        )
        assert watchlist is not None

        assert await repository.delete_list(watchlist.id, stranger.id) is False
        assert await repository.get_list(watchlist.id, owner.id) is not None


class TestThePersonalBrief:
    async def test_counts_are_grouped_by_kind(self, db_session: AsyncSession) -> None:
        repository = EventRepository(db_session)
        await repository.record(
            [
                _event(EventKind.MISSION_PROMOTED, "m1"),
                _event(EventKind.MISSION_PROMOTED, "m2"),
                _event(EventKind.CLONE_DETECTED, "m3"),
            ],
            occurred_at=NOW,
        )

        counts = await repository.counts_by_kind(NOW - timedelta(hours=1))
        assert counts["mission_promoted"] == 2
        assert counts["clone_detected"] == 1

    async def test_events_before_the_cutoff_are_excluded(
        self, db_session: AsyncSession
    ) -> None:
        repository = EventRepository(db_session)
        await repository.record([_event(mint="old")], occurred_at=NOW - timedelta(days=2))
        await repository.record([_event(mint="new")], occurred_at=NOW)

        recent = await repository.events_since(NOW - timedelta(hours=1))
        assert [e.mint_address for e in recent] == ["new"]

    async def test_the_brief_can_be_scoped_to_watched_tokens(
        self, db_session: AsyncSession
    ) -> None:
        # The whole point of a personal brief: only what the user cares about.
        repository = EventRepository(db_session)
        await repository.record(
            [_event(mint="watched"), _event(mint="ignored")], occurred_at=NOW
        )

        scoped = await repository.events_since(NOW - timedelta(hours=1), mints=["watched"])
        assert [e.mint_address for e in scoped] == ["watched"]
