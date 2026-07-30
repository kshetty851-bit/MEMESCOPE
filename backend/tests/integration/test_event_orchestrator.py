"""Integration tests for the event orchestrator and its REST surface.

The rules worth locking are the transactional ones. A cycle writes events *and*
the cache; if the cache lands without its events the change is lost permanently,
because the cache then claims it was already seen.
"""

from __future__ import annotations

import pathlib
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.v1.endpoints.events as events_module
from app.analysts.lifecycle import MissionState
from app.analysts.research import ResearchPriority
from app.events.detector import DetectedEvent, TokenState
from app.events.orchestrator import EventOrchestrator
from app.events.repository import EventRepository
from app.models.intelligence import (
    AnalystReadingCache,
    EventKind,
    EventSeverity,
    IntelligenceEvent,
)
from app.models.market import TokenMarketSnapshot
from app.models.token import DiscoveredToken

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

NOW = datetime(2026, 7, 30, 12, tzinfo=UTC)

#: Path parameters validate as base58 mints (32-44 chars). Short ids work for
#: direct repository calls but 422 through the API.
VALID_MINT = "6Quog29HQ5tA5BdnCv3FWpW8WEpdxCsxEpt2TGCZpump"

#: Read once at import, so the assertion below never touches the event loop.
EVENTS_MODULE_SOURCE = pathlib.Path(events_module.__file__ or "").read_text()


async def _token(session: AsyncSession, mint: str, *, count: int = 20) -> DiscoveredToken:
    token = DiscoveredToken(
        mint_address=mint,
        name=f"Probe {mint[-3:]}",
        symbol="PRB",
        signature=f"sig-{uuid.uuid4()}",
        slot=1,
    )
    session.add(token)
    await session.flush()

    for index in range(count):
        session.add(
            TokenMarketSnapshot(
                token_id=token.id,
                mint_address=mint,
                captured_at=NOW - timedelta(minutes=(count - index) * 30),
                price_usd=Decimal("0.001") + Decimal("0.00002") * index,
                market_cap=Decimal(200_000),
                liquidity_usd=Decimal(30_000) + Decimal(200) * index,
                volume_24h=Decimal(40_000),
                volume_1h=Decimal(1_500),
                buy_count_24h=120,
                sell_count_24h=60,
                provider="test",
            )
        )
    await session.flush()
    return token


class TestTheCycleIsTransactional:
    async def test_a_first_cycle_records_events_and_seeds_the_cache(
        self, db_session: AsyncSession
    ) -> None:
        await _token(db_session, "mint-cycle-1")
        summary = await EventOrchestrator(db_session).run_cycle(["mint-cycle-1"], now=NOW)

        assert summary.analysed == 1
        assert summary.cache_misses == 1
        assert summary.events_generated == 1
        assert summary.failures == 0

        events = await db_session.scalar(select(func.count()).select_from(IntelligenceEvent))
        cached = await db_session.scalar(select(func.count()).select_from(AnalystReadingCache))
        # Both sides landed, which is the invariant the transaction exists for.
        assert events == 1
        assert cached == 1

    async def test_a_second_cycle_is_silent_when_nothing_moved(
        self, db_session: AsyncSession
    ) -> None:
        # The whole product promise: no interruption without a change.
        await _token(db_session, "mint-quiet")
        orchestrator = EventOrchestrator(db_session)
        await orchestrator.run_cycle(["mint-quiet"], now=NOW)
        second = await orchestrator.run_cycle(["mint-quiet"], now=NOW + timedelta(minutes=15))

        assert second.analysed == 1
        assert second.cache_hits == 1
        assert second.changed == 0
        assert second.events_generated == 0

    async def test_one_bad_token_does_not_cost_the_batch(
        self, db_session: AsyncSession
    ) -> None:
        # A mint with no market history cannot be observed; the rest must still
        # be processed rather than the cycle aborting.
        await _token(db_session, "mint-good")
        summary = await EventOrchestrator(db_session).run_cycle(
            ["mint-good", "mint-does-not-exist"], now=NOW
        )
        assert summary.analysed == 1
        assert summary.failures == 0

    async def test_an_empty_cycle_is_free_and_reports_elapsed_time(
        self, db_session: AsyncSession
    ) -> None:
        summary = await EventOrchestrator(db_session).run_cycle([], now=NOW)
        assert summary.analysed == 0
        assert summary.events_generated == 0
        assert summary.elapsed_ms >= 0

    async def test_the_summary_is_serialisable_telemetry(
        self, db_session: AsyncSession
    ) -> None:
        await _token(db_session, "mint-telemetry")
        summary = await EventOrchestrator(db_session).run_cycle(["mint-telemetry"], now=NOW)
        payload = summary.as_dict()

        for key in (
            "analysed",
            "changed",
            "events_generated",
            "events_skipped",
            "cache_hits",
            "cache_misses",
            "failures",
            "elapsed_ms",
        ):
            assert key in payload

    async def test_rerunning_the_same_moment_does_not_duplicate(
        self, db_session: AsyncSession
    ) -> None:
        # A retry or a racing worker must not double-report.
        await _token(db_session, "mint-retry")
        orchestrator = EventOrchestrator(db_session)
        await orchestrator.run_cycle(["mint-retry"], now=NOW)

        # Clear the cache to force re-detection at the identical timestamp.
        await db_session.execute(
            AnalystReadingCache.__table__.delete().where(
                AnalystReadingCache.mint_address == "mint-retry"
            )
        )
        again = await orchestrator.run_cycle(["mint-retry"], now=NOW)

        assert again.events_skipped == 1
        assert again.events_generated == 0
        total = await db_session.scalar(select(func.count()).select_from(IntelligenceEvent))
        assert total == 1


class TestTheRestSurface:
    async def test_events_are_paginated_and_echo_their_filters(
        self, db_session: AsyncSession, client: AsyncClient
    ) -> None:
        repository = EventRepository(db_session)
        for index in range(5):
            await repository.record(
                [
                    DetectedEvent(
                        mint_address=f"m{index}",
                        kind=EventKind.MISSION_PROMOTED,
                        severity=EventSeverity.NOTABLE,
                        summary="Mission status moved.",
                    )
                ],
                occurred_at=datetime.now(UTC) - timedelta(minutes=index),
            )
        await db_session.commit()

        response = await client.get("/api/v1/events", params={"page_size": 2, "hours": 24})
        assert response.status_code == 200
        body = response.json()

        assert body["total"] >= 5
        assert len(body["items"]) == 2
        assert body["applied_filters"]["hours"] == "24"

    async def test_a_strict_filter_returns_an_empty_page_not_an_error(
        self, db_session: AsyncSession, client: AsyncClient
    ) -> None:
        # An empty page caused by a filter must be distinguishable from an
        # empty log, which is what applied_filters is for.
        response = await client.get("/api/v1/events", params={"kind": "clone_resolved"})
        assert response.status_code == 200
        assert response.json()["total"] == 0
        assert response.json()["applied_filters"]["kind"] == "clone_resolved"

    async def test_filtering_happens_in_sql_not_in_the_client(
        self, db_session: AsyncSession, client: AsyncClient
    ) -> None:
        repository = EventRepository(db_session)
        await repository.record(
            [
                DetectedEvent(
                    mint_address="wanted",
                    kind=EventKind.CLONE_DETECTED,
                    severity=EventSeverity.URGENT,
                    summary="Clone risk rose.",
                ),
                DetectedEvent(
                    mint_address="unwanted",
                    kind=EventKind.MISSION_PROMOTED,
                    severity=EventSeverity.NOTABLE,
                    summary="Mission status moved.",
                ),
            ],
            occurred_at=datetime.now(UTC),
        )
        await db_session.commit()

        response = await client.get("/api/v1/events", params={"kind": "clone_detected"})
        mints = [item["mint_address"] for item in response.json()["items"]]
        assert "wanted" in mints
        assert "unwanted" not in mints

    async def test_an_unknown_event_id_is_a_404(self, client: AsyncClient) -> None:
        response = await client.get(f"/api/v1/events/{uuid.uuid4()}")
        assert response.status_code == 404

    async def test_a_tokens_history_is_newest_first(
        self, db_session: AsyncSession, client: AsyncClient
    ) -> None:
        repository = EventRepository(db_session)
        base = datetime.now(UTC)
        await repository.record(
            [
                DetectedEvent(
                    mint_address=VALID_MINT,
                    kind=EventKind.FIRST_ANALYSED,
                    severity=EventSeverity.INFO,
                    summary="First analysed.",
                )
            ],
            occurred_at=base - timedelta(hours=2),
        )
        await repository.record(
            [
                DetectedEvent(
                    mint_address=VALID_MINT,
                    kind=EventKind.MISSION_PROMOTED,
                    severity=EventSeverity.NOTABLE,
                    summary="Promoted.",
                )
            ],
            occurred_at=base,
        )
        await db_session.commit()

        response = await client.get(f"/api/v1/events/token/{VALID_MINT}")
        kinds = [item["kind"] for item in response.json()]
        assert kinds == ["mission_promoted", "first_analysed"]

    async def test_the_mission_log_is_unscoped(
        self, db_session: AsyncSession, client: AsyncClient
    ) -> None:
        response = await client.get("/api/v1/mission-log", params={"hours": 24})
        assert response.status_code == 200
        assert "applied_filters" in response.json()


class TestTheBriefComesOnlyFromStoredEvents:
    async def test_an_empty_watchlist_says_so_rather_than_returning_everything(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        # Falling through to "no filter" would return the whole platform's
        # activity, which is a feed rather than a brief.
        response = await client.get("/api/v1/brief", headers=auth_headers)
        assert response.status_code == 200
        body = response.json()
        assert body["quiet"] is True
        assert body["entries"] == []
        assert "not watching any projects" in body["summary"]

    async def test_uncategorised_kinds_land_in_other_rather_than_vanishing(
        self, db_session: AsyncSession
    ) -> None:
        from app.api.v1.endpoints.events import BRIEF_BUCKETS, _bucket

        categorised = {kind for kinds in BRIEF_BUCKETS.values() for kind in kinds}
        uncategorised = [k for k in EventKind if k not in categorised]
        assert uncategorised, "fixture assumes at least one uncategorised kind exists"

        rows = [
            IntelligenceEvent(
                mint_address="m",
                kind=uncategorised[0],
                severity=EventSeverity.INFO,
                summary="x",
                occurred_at=NOW,
            )
        ]
        counts = _bucket(rows)
        assert counts.other == 1

    def test_the_brief_never_recomputes_analyst_logic(self) -> None:
        # It reads the log and nothing else. If it imported the analysts it
        # could disagree with the events it is summarising, and a user reading
        # both would have no way to tell which was right.
        #
        # Synchronous and read at import time: the source is inspected on disk,
        # which is blocking IO and has no business on the event loop.
        assert "from app.analysts" not in EVENTS_MODULE_SOURCE
        assert "orchestrator" not in EVENTS_MODULE_SOURCE


class TestRegressionsFromPhase16Hold:
    async def test_score_delta_below_the_bar_still_emits_nothing(self) -> None:
        from app.events.detector import detect

        before = TokenState(
            mint_address="m",
            mission_state=MissionState.ORBIT,
            research_priority=ResearchPriority.MEDIUM,
            liquidity_score=Decimal(60),
        )
        after = TokenState(
            mint_address="m",
            mission_state=MissionState.ORBIT,
            research_priority=ResearchPriority.MEDIUM,
            liquidity_score=Decimal(70),
        )
        assert detect(before, after) == []

    async def test_risk_inversion_still_holds(self) -> None:
        from app.events.detector import detect

        before = TokenState(mint_address="m", risk_score=Decimal(20))
        after = TokenState(mint_address="m", risk_score=Decimal(80))
        # Higher risk score is safer, so a rise resolves risk.
        assert detect(before, after)[0].kind is EventKind.RISK_RESOLVED

    async def test_first_analysed_still_fires_once(self) -> None:
        from app.events.detector import detect

        events = detect(None, TokenState(mint_address="m", mission_state=MissionState.ORBIT))
        assert len(events) == 1
        assert events[0].kind is EventKind.FIRST_ANALYSED
