"""Provider analytics against real rows, and the endpoint that serves them.

The derivations are covered by literals in `tests/unit/test_provider_analytics`.
What needs a database is the aggregation itself: the counts are grouped across
two joins, and the one that is easy to get wrong — lifetime — is summed over a
different grain from everything else.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market import TradingStatus
from app.models.opportunity import Opportunity, OpportunitySignal
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

NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
MINT = "HHbRJ9Fw2tPxETGSsaeQhpgdizfVafLvXK7eo5mwpump"
OTHER = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
PROVIDER = "fresh_graduation"


async def _opportunity(
    session: AsyncSession,
    mint: str,
    *,
    generation: int = 1,
    status: OpportunityStatus = OpportunityStatus.ACTIVE,
    closed_after: timedelta | None = None,
) -> Opportunity:
    token = await TokenRepository(session).insert_if_absent(
        {
            "mint_address": mint,
            "signature": f"sig-{mint}-{generation}",
            "slot": 1,
            "discovered_at": NOW - timedelta(days=1),
        }
    )
    if token is None:
        token = await TokenRepository(session).get_by_mint(mint)
    assert token is not None
    await MarketSnapshotRepository(session).add_snapshot(
        {
            "token_id": token.id,
            "mint_address": mint,
            "captured_at": NOW,
            "price_usd": Decimal("0.001"),
            "dex_name": "pumpswap",
            "trading_status": TradingStatus.TRADING,
            "provider": "test",
        }
    )
    opportunity = Opportunity(
        token_id=token.id,
        mint_address=mint,
        generation=generation,
        status=status.value,
        stage=OpportunityStage.FRESH_GRADUATION.value,
        detected_at=NOW,
        last_confirmed_at=NOW,
        closed_at=None if closed_after is None else NOW + closed_after,
    )
    session.add(opportunity)
    await session.flush()
    return opportunity


async def _signal(
    session: AsyncSession,
    opportunity: Opportunity,
    *,
    provider_id: str = PROVIDER,
    signal_type: SignalType = SignalType.FRESH_GRADUATION,
    status: SignalStatus = SignalStatus.ACTIVE,
    confirmations: int = 2,
    confidence: Decimal = Decimal(60),
) -> None:
    session.add(
        OpportunitySignal(
            opportunity_id=opportunity.id,
            mint_address=opportunity.mint_address,
            signal_type=signal_type.value,
            provider_id=provider_id,
            status=status.value,
            severity="notable",
            strength=Decimal(50),
            confidence=confidence,
            confirmations=confirmations,
            observations=6,
            detected_at=NOW,
            last_confirmed_at=NOW,
            expires_at=NOW + timedelta(hours=48),
        )
    )
    await session.flush()


class TestAggregation:
    async def test_it_counts_signals_opportunities_and_states(
        self, db_session: AsyncSession
    ) -> None:
        live = await _opportunity(db_session, MINT)
        await _signal(db_session, live, confirmations=2)
        closed = await _opportunity(
            db_session, OTHER, status=OpportunityStatus.CLOSED, closed_after=timedelta(hours=2)
        )
        await _signal(db_session, closed, status=SignalStatus.EXPIRED, confirmations=1)

        totals = await OpportunityRepository(db_session).provider_totals(
            required_confirmations=2
        )

        record = totals[PROVIDER]
        assert record.signals == 2
        assert record.opportunities == 2
        assert record.confirmed == 1
        assert record.expired == 1
        assert record.closed == 1

    async def test_one_lifetime_is_counted_once_however_many_signals_carry_it(
        self, db_session: AsyncSession
    ) -> None:
        """Lifetime belongs to the opportunity, not to each signal on it.

        Summed at the signal grain, a provider holding two signal types on one
        closed opportunity would count that single two-hour life twice and
        report an average no opportunity ever had.
        """
        closed = await _opportunity(
            db_session,
            MINT,
            status=OpportunityStatus.CLOSED,
            closed_after=timedelta(hours=2),
        )
        await _signal(db_session, closed, signal_type=SignalType.FRESH_GRADUATION)
        await _signal(db_session, closed, signal_type=SignalType.NEAR_GRADUATION)

        totals = await OpportunityRepository(db_session).provider_totals(
            required_confirmations=2
        )

        record = totals[PROVIDER]
        assert record.signals == 2
        assert record.lifetime_samples == 1
        assert record.lifetime_seconds_total == Decimal(7_200)

    async def test_a_live_opportunity_contributes_no_lifetime(
        self, db_session: AsyncSession
    ) -> None:
        live = await _opportunity(db_session, MINT)
        await _signal(db_session, live)

        totals = await OpportunityRepository(db_session).provider_totals(
            required_confirmations=2
        )

        assert totals[PROVIDER].lifetime_samples == 0

    async def test_archived_generations_still_count(
        self, db_session: AsyncSession
    ) -> None:
        """A provider's record must not improve because its calls settled.

        The permanent record is the point of measuring at all — excluding
        archived rows would quietly rebase every ratio on recent history.
        """
        archived = await _opportunity(
            db_session,
            MINT,
            status=OpportunityStatus.ARCHIVED,
            closed_after=timedelta(hours=1),
        )
        await _signal(db_session, archived, status=SignalStatus.EXPIRED)

        totals = await OpportunityRepository(db_session).provider_totals(
            required_confirmations=2
        )

        assert totals[PROVIDER].signals == 1
        assert totals[PROVIDER].lifetime_samples == 1

    async def test_providers_are_counted_separately(
        self, db_session: AsyncSession
    ) -> None:
        opportunity = await _opportunity(db_session, MINT)
        await _signal(db_session, opportunity, provider_id=PROVIDER)
        await _signal(
            db_session,
            opportunity,
            provider_id="near_graduation",
            signal_type=SignalType.NEAR_GRADUATION,
            confirmations=1,
        )

        totals = await OpportunityRepository(db_session).provider_totals(
            required_confirmations=2
        )

        assert totals[PROVIDER].confirmed == 1
        assert totals["near_graduation"].confirmed == 0


class TestEndpoint:
    async def test_every_registered_provider_is_listed(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Including the ones that have never emitted.

        A provider missing from the list is indistinguishable from a provider
        that does not exist, and the second is what an operator needs to know.
        """
        response = await client.get("/api/v1/opportunities/providers")

        assert response.status_code == 200
        body = response.json()
        ids = {item["provider_id"] for item in body["providers"]}
        assert {"fresh_graduation", "near_graduation"} <= ids

    async def test_precision_is_reported_absent_with_its_reason(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Fresh graduation reports a completed change, so precision does not
        apply to it — a different gap from "not resolved yet", and Sprint 12
        made the two distinguishable rather than collapsing both to zero."""
        opportunity = await _opportunity(db_session, MINT)
        await _signal(db_session, opportunity)
        await db_session.commit()

        body = (await client.get("/api/v1/opportunities/providers")).json()

        record = next(
            item for item in body["providers"] if item["provider_id"] == PROVIDER
        )
        assert record["precision"] is None
        assert "not forecasts" in record["precision_unavailable_reason"]
        assert record["hit_rate"] is not None

    async def test_a_predictive_provider_waits_rather_than_declining(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        body = (await client.get("/api/v1/opportunities/providers")).json()

        record = next(
            item for item in body["providers"] if item["provider_id"] == "breakout"
        )
        assert "has resolved yet" in record["precision_unavailable_reason"]

    async def test_the_route_is_not_read_as_a_mint(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """`/providers` is declared before `/{mint}`; registered the other way
        round it would be matched as a token called "providers"."""
        response = await client.get("/api/v1/opportunities/providers")

        assert response.status_code == 200
        assert "providers" in response.json()
