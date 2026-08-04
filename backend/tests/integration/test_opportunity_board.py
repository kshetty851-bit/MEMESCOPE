"""`GET /api/v1/opportunities` — the read path.

The property that drives this design is asserted first: the board must be
correct even if the expiry sweep has never run. Everything else follows from
it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.opportunity import Opportunity, OpportunitySignal
from app.opportunities.models import (
    OpportunityStage,
    OpportunityStatus,
    SignalSeverity,
    SignalStatus,
    SignalType,
)
from app.repositories.token import TokenRepository

pytestmark = pytest.mark.integration

API = settings.API_V1_PREFIX
BOARD = f"{API}/opportunities"
NOW = datetime.now(UTC)


@pytest.fixture(autouse=True)
def _engine_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "FEATURE_OPPORTUNITY_ENGINE_ENABLED", True)


async def _opportunity(
    session: AsyncSession,
    mint: str,
    *,
    status: OpportunityStatus = OpportunityStatus.ACTIVE,
    stage: OpportunityStage = OpportunityStage.FRESH_GRADUATION,
    priority: Decimal = Decimal("60.00"),
    generation: int = 1,
    name: str | None = "Test Token",
) -> Opportunity:
    tokens = TokenRepository(session)
    # `insert_if_absent` returns None when the row already exists — which it
    # does for the second generation of the same mint.
    token = await tokens.insert_if_absent(
        {
            "mint_address": mint,
            "signature": f"sig-{mint}",
            "slot": 1,
            "name": name,
            "symbol": "TEST",
            "discovered_at": NOW - timedelta(days=1),
        }
    ) or await tokens.get_by_mint(mint)
    assert token is not None
    opportunity = Opportunity(
        token_id=token.id,
        mint_address=mint,
        generation=generation,
        status=status.value,
        stage=stage.value,
        priority=priority,
        priority_band="high",
        confidence=Decimal("55.00"),
        detected_at=NOW - timedelta(hours=1),
        last_confirmed_at=NOW - timedelta(minutes=5),
    )
    session.add(opportunity)
    await session.flush()
    return opportunity


async def _signal(
    session: AsyncSession,
    opportunity: Opportunity,
    *,
    signal_type: SignalType = SignalType.FRESH_GRADUATION,
    status: SignalStatus = SignalStatus.ACTIVE,
    expires_in: int = 3600,
    provider: str = "fresh_graduation",
    confidence: Decimal = Decimal("55.00"),
) -> OpportunitySignal:
    signal = OpportunitySignal(
        opportunity_id=opportunity.id,
        mint_address=opportunity.mint_address,
        signal_type=signal_type.value,
        provider_id=provider,
        status=status.value,
        severity=SignalSeverity.MAJOR.value,
        strength=Decimal("100.00"),
        confidence=confidence,
        confirmations=2,
        observations=6,
        detected_at=NOW - timedelta(minutes=30),
        last_confirmed_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(seconds=expires_in),
        observed_at=NOW - timedelta(minutes=5),
        reason_codes=["graduated_from_bonding_curve", "trading_venue_changed"],
        evidence=[
            {"label": "Previous venue", "value": "pumpfun", "detail": "Bonding curve"},
            {"label": "Current venue", "value": "pumpswap", "detail": "Graduated pool"},
        ],
    )
    session.add(signal)
    await session.flush()
    return signal


def _mint(suffix: str) -> str:
    return f"{uuid.uuid4().hex[:32]}{suffix}"[:44]


class TestCorrectnessWithoutTheSweep:
    async def test_a_lapsed_signal_leaves_the_board_before_any_sweep_runs(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The property this whole read path is built on.

        `expires_at` passes without anything writing a row. The opportunity is
        still `ACTIVE` and the signal still `ACTIVE` — no sweep has touched
        them — and the board must already exclude it. Trusting a background job
        to have run is the assumption that let discovery die for four days.
        """
        mint = _mint("lapse")
        opportunity = await _opportunity(db_session, mint)
        await _signal(db_session, opportunity, expires_in=-1)

        body = (await client.get(BOARD)).json()

        assert body["items"] == []
        # Nothing was corrected on the way past: the read is authoritative.
        assert opportunity.status == OpportunityStatus.ACTIVE.value

    async def test_a_token_that_stopped_being_enriched_falls_off_on_its_own(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """No gap detection required — the signals simply age out."""
        mint = _mint("stale")
        opportunity = await _opportunity(db_session, mint)
        await _signal(db_session, opportunity, expires_in=-86_400)

        assert (await client.get(BOARD)).json()["items"] == []

    async def test_an_unexpired_signal_is_on_the_board(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        mint = _mint("live")
        opportunity = await _opportunity(db_session, mint)
        await _signal(db_session, opportunity)

        items = (await client.get(BOARD)).json()["items"]

        assert len(items) == 1
        assert items[0]["mint_address"] == mint

    async def test_an_expired_signal_status_is_excluded_even_if_unexpired(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Both halves of the predicate matter.

        `status` is what the engine maintains; `expires_at` is what is true
        regardless. Either one alone lets something wrong onto the board.
        """
        mint = _mint("marked")
        opportunity = await _opportunity(db_session, mint)
        await _signal(db_session, opportunity, status=SignalStatus.EXPIRED, expires_in=3600)

        assert (await client.get(BOARD)).json()["items"] == []

    async def test_a_closed_opportunity_never_appears(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        mint = _mint("closed")
        opportunity = await _opportunity(db_session, mint, status=OpportunityStatus.CLOSED)
        await _signal(db_session, opportunity)

        assert (await client.get(BOARD)).json()["items"] == []


class TestOneCardPerToken:
    async def test_several_signals_render_as_one_card(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Near Graduation + Pre-Breakout + Liquidity Surge is one card.

        Stage and signal are orthogonal, so they can never duplicate a token.
        """
        mint = _mint("multi")
        opportunity = await _opportunity(db_session, mint)
        for signal_type in (
            SignalType.FRESH_GRADUATION,
            SignalType.PRE_BREAKOUT,
            SignalType.LIQUIDITY_EXPANSION,
        ):
            await _signal(
                db_session,
                opportunity,
                signal_type=signal_type,
                provider=signal_type.value[:20],
            )

        items = (await client.get(BOARD)).json()["items"]

        assert len(items) == 1
        assert len(items[0]["signals"]) == 3

    async def test_lapsed_badges_are_not_shown_on_a_live_card(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A card must not show a badge the board no longer counts.

        The signal query uses the same freshness predicate as the header query,
        so the two cannot disagree.
        """
        mint = _mint("mixed")
        opportunity = await _opportunity(db_session, mint)
        await _signal(db_session, opportunity)
        await _signal(
            db_session,
            opportunity,
            signal_type=SignalType.BREAKOUT,
            provider="breakout",
            expires_in=-1,
        )

        items = (await client.get(BOARD)).json()["items"]

        assert len(items) == 1
        assert [signal["signal_type"] for signal in items[0]["signals"]] == [
            SignalType.FRESH_GRADUATION.value
        ]


class TestOrdering:
    async def test_ranked_by_priority(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        for priority in (Decimal("10.00"), Decimal("90.00"), Decimal("50.00")):
            opportunity = await _opportunity(
                db_session, _mint(f"p{priority}"), priority=priority
            )
            await _signal(db_session, opportunity)

        items = (await client.get(BOARD)).json()["items"]

        assert [item["priority"] for item in items] == ["90.00", "50.00", "10.00"]

    async def test_the_order_is_total_and_stable(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Ties must break deterministically.

        A partial order means an item appearing twice, or not at all, between
        pages — and an unordered LIMIT is what caused the score-sweep livelock.
        """
        for index in range(5):
            opportunity = await _opportunity(
                db_session, _mint(f"t{index}"), priority=Decimal("50.00")
            )
            await _signal(db_session, opportunity)

        first = (await client.get(BOARD)).json()["items"]
        second = (await client.get(BOARD)).json()["items"]

        assert [item["mint_address"] for item in first] == [
            item["mint_address"] for item in second
        ]


class TestPagination:
    async def test_has_more_without_counting_the_board(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """No `total`: an unconditional count is a measured mistake.

        Two of them cost 7.1 ms against a 0.4 ms ranking query on `/scores/top`.
        """
        for index in range(4):
            opportunity = await _opportunity(db_session, _mint(f"pg{index}"))
            await _signal(db_session, opportunity)

        body = (await client.get(f"{BOARD}?page=1&page_size=2")).json()

        assert len(body["items"]) == 2
        assert body["has_more"] is True
        assert "total" not in body

    async def test_the_last_page_reports_no_more(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        for index in range(3):
            opportunity = await _opportunity(db_session, _mint(f"lp{index}"))
            await _signal(db_session, opportunity)

        body = (await client.get(f"{BOARD}?page=2&page_size=2")).json()

        assert len(body["items"]) == 1
        assert body["has_more"] is False

    async def test_pages_do_not_overlap(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        for index in range(6):
            opportunity = await _opportunity(
                db_session, _mint(f"ov{index}"), priority=Decimal("50.00")
            )
            await _signal(db_session, opportunity)

        first = (await client.get(f"{BOARD}?page=1&page_size=3")).json()["items"]
        second = (await client.get(f"{BOARD}?page=2&page_size=3")).json()["items"]

        mints = [item["mint_address"] for item in first + second]
        assert len(mints) == len(set(mints)) == 6


class TestFilters:
    async def test_filtering_by_signal_type(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        graduated = await _opportunity(db_session, _mint("fg"))
        await _signal(db_session, graduated)
        breaking = await _opportunity(db_session, _mint("bo"))
        await _signal(
            db_session, breaking, signal_type=SignalType.BREAKOUT, provider="breakout"
        )

        body = (await client.get(f"{BOARD}?signal_type=breakout")).json()

        assert len(body["items"]) == 1
        assert body["items"][0]["mint_address"] == breaking.mint_address

    async def test_filtering_by_stage(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        fresh = await _opportunity(db_session, _mint("fr"))
        await _signal(db_session, fresh)
        established = await _opportunity(
            db_session, _mint("es"), stage=OpportunityStage.ESTABLISHED
        )
        await _signal(db_session, established)

        body = (await client.get(f"{BOARD}?stage=established")).json()

        assert len(body["items"]) == 1
        assert body["items"][0]["stage"] == OpportunityStage.ESTABLISHED.value

    async def test_an_unknown_filter_returns_an_empty_page_not_a_422(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A rejected value should not read as though the board is broken."""
        opportunity = await _opportunity(db_session, _mint("uf"))
        await _signal(db_session, opportunity)

        response = await client.get(f"{BOARD}?signal_type=not_a_real_signal")

        assert response.status_code == 200
        assert response.json()["items"] == []

    async def test_filters_are_echoed(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """So an empty page caused by a strict filter is distinguishable from
        an empty board — the convention `/radar` and `/scores/top` follow."""
        body = (await client.get(f"{BOARD}?signal_type=breakout")).json()
        assert body["applied_filters"]["signal_type"] == "breakout"


class TestRendering:
    async def test_the_explanation_answers_why_now(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        mint = _mint("ex")
        opportunity = await _opportunity(db_session, mint)
        await _signal(db_session, opportunity)

        explanation = (await client.get(BOARD)).json()["items"][0]["signals"][0]["explanation"]

        assert explanation["headline"] == "Freshly graduated"
        assert "bonding curve" in explanation["trigger"]
        assert any("pumpfun" in line for line in explanation["delta"])
        assert any("pumpswap" in line for line in explanation["delta"])

    async def test_the_explanation_declares_what_could_not_be_checked(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The limits clause is where coverage stays honest.

        Without it a card quietly looks complete — which is exactly what the
        platform refuses to do elsewhere with smart money.
        """
        mint = _mint("lim")
        opportunity = await _opportunity(db_session, mint)
        await _signal(db_session, opportunity)

        limits = (await client.get(BOARD)).json()["items"][0]["signals"][0]["explanation"][
            "limits"
        ]

        assert limits
        assert any("Liquidity" in line for line in limits)
        assert any("Holder" in line for line in limits)

    async def test_prose_is_not_stored(
        self, db_session: AsyncSession, client: AsyncClient
    ) -> None:
        """Rewording an explanation must be a deploy, not a migration."""
        mint = _mint("np")
        opportunity = await _opportunity(db_session, mint)
        signal = await _signal(db_session, opportunity)

        assert not hasattr(signal, "explanation")
        assert signal.reason_codes == [
            "graduated_from_bonding_curve",
            "trading_venue_changed",
        ]

    async def test_staleness_is_surfaced_not_hidden(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """`priority` is as of the last evaluation.

        A reader is entitled to see that a ranking is minutes old rather than
        be shown a silently re-sorted board.
        """
        mint = _mint("age")
        opportunity = await _opportunity(db_session, mint)
        await _signal(db_session, opportunity)

        item = (await client.get(BOARD)).json()["items"][0]

        assert item["confirmed_age_seconds"] >= 0
        assert item["last_confirmed_at"] is not None
        assert item["signals"][0]["expires_in_seconds"] > 0

    async def test_identity_is_joined_not_copied(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Name and symbol live in `discovered_tokens`.

        Joined at read time, so metadata that resolves later shows up without a
        backfill.
        """
        mint = _mint("id")
        opportunity = await _opportunity(db_session, mint, name="Late Metadata")
        await _signal(db_session, opportunity)

        item = (await client.get(BOARD)).json()["items"][0]

        assert item["name"] == "Late Metadata"
        assert item["symbol"] == "TEST"

    async def test_confidence_is_reported_below_strength(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        mint = _mint("cf")
        opportunity = await _opportunity(db_session, mint)
        await _signal(db_session, opportunity)

        signal = (await client.get(BOARD)).json()["items"][0]["signals"][0]

        assert Decimal(signal["confidence"]) < Decimal(signal["strength"])


class TestSingleOpportunity:
    async def test_it_returns_the_live_opportunity(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        mint = _mint("one")
        opportunity = await _opportunity(db_session, mint)
        await _signal(db_session, opportunity)

        body = (await client.get(f"{BOARD}/{mint}")).json()

        assert body["mint_address"] == mint
        assert body["generation"] == 1

    async def test_a_past_generation_is_addressable(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The permanent record must stay readable after a token reopens."""
        mint = _mint("gen")
        await _opportunity(
            db_session,
            mint,
            status=OpportunityStatus.ARCHIVED,
            generation=1,
            priority=Decimal("20.00"),
        )
        current = await _opportunity(db_session, mint, generation=2)
        await _signal(db_session, current)

        live = (await client.get(f"{BOARD}/{mint}")).json()
        past = (await client.get(f"{BOARD}/{mint}?generation=1")).json()

        assert live["generation"] == 2
        assert past["generation"] == 1
        assert past["status"] == OpportunityStatus.ARCHIVED.value

    async def test_an_unknown_token_is_a_404(self, client: AsyncClient) -> None:
        assert (await client.get(f"{BOARD}/{_mint('missing')}")).status_code == 404


class TestFeatureFlag:
    async def test_the_board_is_empty_while_the_engine_is_off(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Empty, not absent.

        A 404 would read as "this platform has no such feature"; the honest
        answer is "it is not switched on here".
        """
        opportunity = await _opportunity(db_session, _mint("off"))
        await _signal(db_session, opportunity)
        monkeypatch.setattr(settings, "FEATURE_OPPORTUNITY_ENGINE_ENABLED", False)

        response = await client.get(BOARD)

        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["applied_filters"]["engine_enabled"] is False


class TestEmptyBoard:
    async def test_an_empty_board_is_a_valid_answer(self, client: AsyncClient) -> None:
        """Nothing changed is information, not a fault.

        It must never be resolved by relaxing admission — the recorded
        accepted risk in ARCHITECTURE_DECISIONS.md §17.
        """
        response = await client.get(BOARD)

        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["has_more"] is False
        assert body["applied_filters"]["engine_enabled"] is True


class TestQueryCost:
    async def test_the_page_costs_a_bounded_number_of_queries(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch: Any
    ) -> None:
        """Four queries regardless of page size — never N+1.

        Headers, their signals, their identities, and the has-more probe. A
        query per card is what turns a board into a scan.
        """
        for index in range(10):
            opportunity = await _opportunity(db_session, _mint(f"q{index}"))
            await _signal(db_session, opportunity)

        executed: list[str] = []
        original = AsyncSession.execute

        async def _counting(self: AsyncSession, statement: Any, *args: Any, **kwargs: Any):
            executed.append(str(statement)[:40])
            return await original(self, statement, *args, **kwargs)

        monkeypatch.setattr(AsyncSession, "execute", _counting)
        await client.get(f"{BOARD}?page_size=10")

        assert len(executed) <= 5, f"expected a bounded query count, got {len(executed)}"
