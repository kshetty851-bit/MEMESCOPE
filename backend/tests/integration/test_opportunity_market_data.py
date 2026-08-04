"""Market data on the opportunity board.

Before this the board carried no price, liquidity, volume or age, so a trader
could read a signal and had no way to evaluate or act on it. What is asserted
here is mostly about *absence*: a token nobody has priced must render as having
no market, never as being worth zero, and a token younger than the comparison
window must show no 24-hour change rather than a flat 0%.
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
from app.repositories.market import MarketSnapshotRepository
from app.repositories.token import TokenRepository

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)
MINT = "MarketDataMint111111111111111111111111111111"


async def _token(session: AsyncSession, mint: str, *, age: timedelta) -> object:
    token = await TokenRepository(session).insert_if_absent(
        {
            "mint_address": mint,
            "signature": f"sig-{mint}",
            "slot": 1,
            "discovered_at": NOW - age,
            "block_time": NOW - age,
            "name": "Market Probe",
            "symbol": "MKT",
        }
    )
    assert token is not None
    return token


async def _snapshot(
    session: AsyncSession, token: object, mint: str, *, at: datetime, price: str
) -> None:
    await MarketSnapshotRepository(session).add_snapshot(
        {
            "token_id": token.id,  # type: ignore[attr-defined]
            "mint_address": mint,
            "captured_at": at,
            "price_usd": Decimal(price),
            "market_cap": Decimal("124000"),
            "liquidity_usd": Decimal("18000"),
            "volume_24h": Decimal("89000"),
            "dex_name": "pumpswap",
            "trading_status": TradingStatus.TRADING,
            "provider": "test",
        }
    )


async def _opportunity(session: AsyncSession, token: object, mint: str) -> Opportunity:
    opportunity = Opportunity(
        token_id=token.id,  # type: ignore[attr-defined]
        mint_address=mint,
        generation=1,
        status=OpportunityStatus.ACTIVE.value,
        stage=OpportunityStage.FRESH_GRADUATION.value,
        detected_at=NOW,
        last_confirmed_at=NOW,
    )
    session.add(opportunity)
    await session.flush()
    # The board deliberately requires at least one *unexpired* signal, so an
    # opportunity without one is correctly invisible there. Attach one rather
    # than weaken the query.
    session.add(
        OpportunitySignal(
            opportunity_id=opportunity.id,
            mint_address=mint,
            signal_type=SignalType.FRESH_GRADUATION.value,
            provider_id="fresh_graduation",
            status=SignalStatus.ACTIVE.value,
            severity="major",
            strength=Decimal(100),
            confidence=Decimal(30),
            confirmations=2,
            observations=12,
            detected_at=NOW,
            last_confirmed_at=NOW,
            expires_at=NOW + timedelta(hours=48),
        )
    )
    await session.flush()
    return opportunity


class TestMarketStrip:
    async def test_a_card_carries_the_figures_needed_to_act(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _token(db_session, MINT, age=timedelta(hours=2))
        await _snapshot(db_session, token, MINT, at=NOW, price="0.000021")
        await _opportunity(db_session, token, MINT)
        await db_session.commit()

        body = (await client.get(f"/api/v1/opportunities/{MINT}")).json()

        market = body["market"]
        assert market is not None
        assert Decimal(market["price_usd"]) == Decimal("0.000021")
        assert Decimal(market["market_cap"]) == Decimal("124000")
        assert Decimal(market["liquidity_usd"]) == Decimal("18000")
        assert Decimal(market["volume_24h"]) == Decimal("89000")
        assert market["dex_name"] == "pumpswap"

    async def test_money_stays_a_string_end_to_end(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """`NUMERIC` in Postgres, string in JSON. A float anywhere between the
        snapshot and the screen is a rounding error waiting to be displayed."""
        token = await _token(db_session, MINT, age=timedelta(hours=2))
        await _snapshot(db_session, token, MINT, at=NOW, price="0.000021")
        await _opportunity(db_session, token, MINT)
        await db_session.commit()

        body = (await client.get(f"/api/v1/opportunities/{MINT}")).json()

        assert isinstance(body["market"]["price_usd"], str)
        assert isinstance(body["market"]["market_cap"], str)

    async def test_age_comes_from_the_chain_not_from_detection(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A token four minutes old and one four days old are different risks
        even when every other figure matches."""
        token = await _token(db_session, MINT, age=timedelta(hours=6))
        await _snapshot(db_session, token, MINT, at=NOW, price="0.000021")
        await _opportunity(db_session, token, MINT)
        await db_session.commit()

        body = (await client.get(f"/api/v1/opportunities/{MINT}")).json()

        assert 21_000 < body["age_seconds"] < 22_500  # ~6h


class TestAbsence:
    async def test_an_unpriced_token_has_no_market_rather_than_a_zero(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The whole point. A token nobody has priced is not a token worth $0,
        and rendering one as the other is the estimate this platform refuses."""
        token = await _token(db_session, MINT, age=timedelta(minutes=5))
        await _opportunity(db_session, token, MINT)
        await db_session.commit()

        body = (await client.get(f"/api/v1/opportunities/{MINT}")).json()

        assert body["market"] is None

    async def test_a_token_younger_than_the_window_shows_no_24h_change(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """"Unchanged" and "we were not watching yet" are different claims.
        Only one of them is true for a token minutes old."""
        token = await _token(db_session, MINT, age=timedelta(minutes=10))
        await _snapshot(db_session, token, MINT, at=NOW, price="0.000021")
        await _opportunity(db_session, token, MINT)
        await db_session.commit()

        body = (await client.get(f"/api/v1/opportunities/{MINT}")).json()

        assert body["market"]["change_24h_pct"] is None

    async def test_change_is_computed_when_both_ends_were_observed(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _token(db_session, MINT, age=timedelta(days=3))
        await _snapshot(
            db_session, token, MINT, at=NOW - timedelta(hours=30), price="0.000010"
        )
        await _snapshot(db_session, token, MINT, at=NOW, price="0.000015")
        await _opportunity(db_session, token, MINT)
        await db_session.commit()

        body = (await client.get(f"/api/v1/opportunities/{MINT}")).json()

        assert Decimal(body["market"]["change_24h_pct"]) == Decimal("50.00")

    async def test_the_reading_carries_its_own_timestamp(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A stale price must be visibly stale rather than silently current."""
        token = await _token(db_session, MINT, age=timedelta(days=1))
        await _snapshot(
            db_session, token, MINT, at=NOW - timedelta(minutes=40), price="0.000021"
        )
        await _opportunity(db_session, token, MINT)
        await db_session.commit()

        body = (await client.get(f"/api/v1/opportunities/{MINT}")).json()

        assert body["market"]["captured_at"] is not None


class TestBatching:
    async def test_the_board_resolves_a_page_without_a_query_per_card(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Batched deliberately: a query per card turns one page load into
        twenty-five round trips."""
        for index in range(3):
            mint = f"BatchMint{index}".ljust(44, "1")[:44]
            token = await _token(db_session, mint, age=timedelta(hours=1))
            await _snapshot(db_session, token, mint, at=NOW, price="0.000021")
            await _opportunity(db_session, token, mint)
        await db_session.commit()

        body = (await client.get("/api/v1/opportunities")).json()

        priced = [item for item in body["items"] if item["market"] is not None]
        assert len(priced) >= 3
        assert all(item["age_seconds"] is not None for item in priced)
