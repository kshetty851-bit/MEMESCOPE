"""Retention expires telemetry and never touches evidence.

The carve-out is the part that matters. `token_market_snapshots` is where an
entry price, an exit price and every trailing-stop decision in between are
recorded, so a retention job that trims it by age alone quietly destroys the
ability to explain a trade. The foreign keys from the decision tables are
`ON DELETE SET NULL`, which means the damage would not even raise — it would
blank the link and carry on.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market import TokenMarketSnapshot, TradingStatus
from app.models.paper import PaperPosition, PaperWallet
from app.models.radar import RadarToken
from app.models.token import DiscoveredToken
from app.workers.retention_tasks import _prune_market_snapshots, _prune_score_history

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)
OLD = NOW - timedelta(days=30)


@pytest.fixture
async def session(test_session_factory):
    """A really-committed session: the prune opens its own, so uncommitted
    fixture data would be invisible to it."""
    async with test_session_factory() as s:
        yield s
        # Committed data is real; take it back out so runs stay independent.
        await s.execute(text("DELETE FROM token_market_snapshots"))
        await s.execute(text("DELETE FROM paper_positions"))
        await s.execute(text("DELETE FROM paper_wallets"))
        await s.execute(text("DELETE FROM radar_tokens"))
        await s.execute(text("DELETE FROM discovered_tokens"))
        await s.commit()


async def _token(session: AsyncSession, mint: str) -> DiscoveredToken:
    token = DiscoveredToken(
        mint_address=mint, signature=f"sig-{mint}", slot=1, discovered_at=OLD
    )
    session.add(token)
    await session.flush()
    return token


async def _snapshot(
    session: AsyncSession, token: DiscoveredToken, *, at: datetime
) -> uuid.UUID:
    row = TokenMarketSnapshot(
        token_id=token.id, mint_address=token.mint_address, captured_at=at,
        price_usd=Decimal("0.001"), trading_status=TradingStatus.TRADING,
        is_verified=False, provider="test",
    )
    session.add(row)
    await session.flush()
    return row.id


async def _count(session: AsyncSession, mint: str) -> int:
    rows = await session.scalars(
        select(TokenMarketSnapshot.id).where(TokenMarketSnapshot.mint_address == mint)
    )
    return len(list(rows.all()))


class TestMarketSnapshotCarveOut:
    async def test_an_ordinary_token_loses_old_snapshots(
        self, session: AsyncSession
    ) -> None:
        token = await _token(session, "RetentionOrdinary" + "1" * 26)
        await _snapshot(session, token, at=OLD)
        await session.commit()

        await _prune_market_snapshots(7)

        assert await _count(session, token.mint_address) == 0

    async def test_an_admitted_token_keeps_its_whole_series(
        self, session: AsyncSession
    ) -> None:
        """A Track Record token must stay explainable forever."""
        token = await _token(session, "RetentionAdmitted" + "1" * 26)
        await _snapshot(session, token, at=OLD)
        session.add(
            RadarToken(
                token_id=token.id, mint_address=token.mint_address,
                first_detected_at=OLD, first_opportunity_score=Decimal("80"),
                first_confidence=Decimal("50"), detection_reason=["test"],
                category="early_momentum", current_opportunity_score=Decimal("80"),
                current_confidence=Decimal("50"), current_category="early_momentum",
                is_active=True, model_version="test",
            )
        )
        await session.commit()

        await _prune_market_snapshots(7)

        assert await _count(session, token.mint_address) == 1

    async def test_a_traded_token_keeps_its_whole_series(
        self, session: AsyncSession
    ) -> None:
        """Entry and exit evidence outlives every retention window."""
        token = await _token(session, "RetentionTraded" + "1" * 28)
        await _snapshot(session, token, at=OLD)
        wallet = PaperWallet(
            strategy_id="retention_test", strategy_version="v1", generation=1,
            starting_balance=Decimal("1000"), started_at=OLD,
        )
        session.add(wallet)
        await session.flush()
        session.add(
            PaperPosition(
                wallet_id=wallet.id, mint_address=token.mint_address, token_id=token.id,
                opened_at=OLD, entry_rank=1, entry_price=Decimal("0.001"),
                size_usd=Decimal("10"), quantity=Decimal("10000"), status="closed",
                peak_price=Decimal("0.001"), last_evaluated_at=OLD,
            )
        )
        await session.commit()

        await _prune_market_snapshots(7)

        # Closed, not open: the previous implementation protected only open
        # positions and would have deleted this.
        assert await _count(session, token.mint_address) == 1

    async def test_recent_snapshots_survive_regardless(
        self, session: AsyncSession
    ) -> None:
        token = await _token(session, "RetentionRecent" + "1" * 28)
        await _snapshot(session, token, at=NOW)
        await session.commit()

        await _prune_market_snapshots(7)

        assert await _count(session, token.mint_address) == 1


class TestScoreHistoryPrune:
    async def test_it_returns_a_count_and_does_not_raise(
        self, session: AsyncSession
    ) -> None:
        assert await _prune_score_history(7) >= 0
