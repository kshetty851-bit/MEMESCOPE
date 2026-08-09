"""Integration tests for Parallel Shadow Wallets (V2-V5) and Strategy Intelligence endpoint.

Verifies:
- GET /api/v1/paper/strategy-intelligence response structure and promotion rules.
- ShadowPaperService review execution, wallet creation, decision recording.
- Idempotency across duplicate review runs.
- Absolute isolation of production V1 Paper Wallet tables.
- Financial independence of V2, V3, V4, V5 shadow wallets.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.market import TradingStatus
from app.models.paper import (
    PaperPosition,
    PaperShadowDecision,
    PaperShadowPosition,
    PaperShadowTradeAudit,
    PaperShadowWallet,
)
from app.models.radar import RadarToken
from app.paper import scheduler as paper_scheduler
from app.paper.execution import ExecutionQuote
from app.paper.scheduler import acquire_paper_review_lock
from app.paper.service import PaperWalletService
from app.paper.shadow import ShadowPaperService
from app.repositories.market import MarketSnapshotRepository
from app.repositories.token import TokenRepository

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC).replace(microsecond=0)


def _make_execution_quote(
    mint: str,
    impact_pct: Decimal = Decimal("0.5"),
) -> ExecutionQuote:
    return ExecutionQuote(
        side="buy",
        model_version="jupiter_v1",
        quoted_at=NOW,
        latency_ms=Decimal(50),
        input_mint="So11111111111111111111111111111111111111112",
        output_mint=mint,
        input_amount_raw="100000000",
        output_amount_raw="1000000000",
        input_decimals=9,
        output_decimals=6,
        input_amount=Decimal(100),
        output_amount=Decimal(100),
        input_amount_usd=Decimal(100),
        output_amount_usd=Decimal(100),
        estimated_price_usd=Decimal("0.05"),
        price_impact_pct=impact_pct,
        context_slot=123456,
        platform_fee_usd=Decimal(0),
        route="Raydium",
        amms=("Raydium",),
        raw={},
    )


@pytest.fixture(autouse=True)
def _wallet_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "FEATURE_PAPER_WALLET_ENABLED", True)
    monkeypatch.setattr(settings, "PAPER_EXECUTION_MODEL", "legacy")


async def _seed_token_and_radar(
    db_session: AsyncSession,
    mint: str,
    score: Decimal = Decimal(75),
    mcap: Decimal = Decimal(35_000),
    liquidity: Decimal = Decimal(10_000),
) -> None:
    token_repo = TokenRepository(db_session)
    token = await token_repo.insert_if_absent(
        {
            "mint_address": mint,
            "signature": f"sig-{mint}",
            "slot": 1,
            "discovered_at": NOW - timedelta(hours=2),
            "block_time": NOW - timedelta(hours=2),
            "name": f"Token {mint}",
            "symbol": mint[:4].upper(),
            "decimals": 6,
        }
    )
    market_repo = MarketSnapshotRepository(db_session)
    await market_repo.add_snapshot(
        {
            "token_id": token.id,  # type: ignore[attr-defined]
            "mint_address": mint,
            "captured_at": NOW - timedelta(minutes=5),
            "price_usd": Decimal("0.05"),
            "market_cap": mcap,
            "liquidity_usd": liquidity,
            "volume_24h": Decimal(100_000),
            "trading_status": TradingStatus.TRADING,
            "provider": "dexscreener",
        }
    )
    radar = RadarToken(
        mint_address=mint,
        token_id=token.id,
        first_detected_at=NOW - timedelta(hours=2),
        first_price=Decimal("0.05"),
        first_market_cap=mcap,
        first_opportunity_score=score,
        first_confidence=Decimal("0.85"),
        category="early_momentum",
        current_opportunity_score=score,
        current_confidence=Decimal("0.85"),
        current_category="early_momentum",
        model_version="v1",
        last_evaluated_at=NOW - timedelta(minutes=5),
        is_active=True,
    )
    db_session.add(radar)
    await db_session.flush()


class TestShadowPaperAPI:
    async def test_get_strategy_intelligence_endpoint(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/paper/strategy-intelligence")
        assert response.status_code == 200
        data = response.json()

        assert data["enabled"] is True
        assert "observed_at" in data
        assert data["promotion_rules"]["minimum_completed_trades"] == 100
        assert data["promotion_rules"]["minimum_profit_factor"] == "1.20"
        assert len(data["wallets"]) == 4

        wallet_codes = [w["code"] for w in data["wallets"]]
        assert wallet_codes == ["v2", "v3", "v4", "v5"]

    async def test_disabled_feature_returns_disabled_state(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "FEATURE_PAPER_WALLET_ENABLED", False)
        response = await client.get("/api/v1/paper/strategy-intelligence")
        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is False
        assert data["wallets"] == []


class TestShadowPaperServiceExecution:
    async def test_review_evaluates_opportunities_and_creates_wallets(
        self,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mint = "probe_shadow_mint_1"
        await _seed_token_and_radar(db_session, mint, score=Decimal(75), mcap=Decimal(35_000))

        monkeypatch.setattr(settings, "PAPER_EXECUTION_MODEL", "jupiter")

        service = ShadowPaperService(db_session)
        service._execution.buy_quote = AsyncMock(return_value=_make_execution_quote(mint))

        outcome = await service.review(now=NOW)
        await db_session.commit()

        assert outcome.evaluated == 4
        assert outcome.candidates >= 1

        wallets = (
            await db_session.scalars(
                select(PaperShadowWallet).order_by(PaperShadowWallet.wallet_code)
            )
        ).all()
        assert len(wallets) == 4

        decisions = (
            await db_session.scalars(
                select(PaperShadowDecision).where(PaperShadowDecision.mint_address == mint)
            )
        ).all()
        assert len(decisions) == 4

        # V2 accepts mcap 35k, score 75
        v2_decision = next(d for d in decisions if d.wallet_code == "v2")
        assert v2_decision.decision == "accepted"
        assert v2_decision.position_id is not None
        v2_position = await db_session.get(PaperShadowPosition, v2_decision.position_id)
        assert v2_position is not None
        assert v2_position.mint_address == mint

        # V4 rejects mcap 35k (requires $50k-$100k)
        v4_decision = next(d for d in decisions if d.wallet_code == "v4")
        assert v4_decision.decision == "rejected"
        assert "market_cap_too_low" in v4_decision.reason_codes

    async def test_review_idempotency_and_duplicate_prevention(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mint = "probe_idempotent_mint"
        await _seed_token_and_radar(db_session, mint, score=Decimal(80), mcap=Decimal(30_000))
        monkeypatch.setattr(settings, "PAPER_EXECUTION_MODEL", "jupiter")

        service = ShadowPaperService(db_session)
        service._execution.buy_quote = AsyncMock(return_value=_make_execution_quote(mint))

        # First review run
        outcome_1 = await service.review(now=NOW)
        await db_session.commit()
        assert outcome_1.decisions == 4

        # Second review run with identical evaluation timestamp
        outcome_2 = await service.review(now=NOW)
        await db_session.commit()
        # Duplicate decisions are skipped via ON CONFLICT DO NOTHING
        assert outcome_2.decisions == 0

        # Check total decision records for this mint remains 4
        decisions = (
            await db_session.scalars(
                select(PaperShadowDecision).where(PaperShadowDecision.mint_address == mint)
            )
        ).all()
        assert len(decisions) == 4
        accepted = [decision for decision in decisions if decision.decision == "accepted"]
        assert accepted
        assert all(decision.position_id is not None for decision in accepted)

        positions = (
            await db_session.scalars(
                select(PaperShadowPosition).where(PaperShadowPosition.mint_address == mint)
            )
        ).all()
        assert len(positions) == len(accepted)

    async def test_v1_isolation(self, db_session: AsyncSession) -> None:
        """Executing ShadowPaperService review must never write to V1 tables."""
        mint = "probe_v1_iso_mint"
        await _seed_token_and_radar(db_session, mint, score=Decimal(80), mcap=Decimal(30_000))

        # Ensure V1 wallet initialized
        v1_service = PaperWalletService(db_session)
        await v1_service.review(now=NOW)
        await db_session.commit()

        v1_positions_before = (await db_session.scalars(select(PaperPosition))).all()

        # Run Shadow review
        shadow_service = ShadowPaperService(db_session)
        await shadow_service.review(now=NOW)
        await db_session.commit()

        v1_positions_after = (await db_session.scalars(select(PaperPosition))).all()
        assert len(v1_positions_before) == len(v1_positions_after)

    async def test_shadow_close_audit_ignores_v1_manual_audit_fields(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Shadow audits must not receive V1-only manual-sell columns."""
        mint = "probe_shadow_audit_close"
        await _seed_token_and_radar(db_session, mint, score=Decimal(75), mcap=Decimal(35_000))
        monkeypatch.setattr(settings, "PAPER_EXECUTION_MODEL", "jupiter")

        service = ShadowPaperService(db_session)
        service._execution.buy_quote = AsyncMock(return_value=_make_execution_quote(mint))
        service._execution.sell_quote = AsyncMock(return_value=_make_execution_quote(mint))

        opened = await service.review(now=NOW)
        await db_session.commit()
        assert opened.opened >= 1

        token = (
            await db_session.scalars(
                select(RadarToken).where(RadarToken.mint_address == mint).limit(1)
            )
        ).one()
        await MarketSnapshotRepository(db_session).add_snapshot(
            {
                "token_id": token.token_id,
                "mint_address": mint,
                "captured_at": NOW + timedelta(minutes=1),
                "price_usd": Decimal("0.03"),
                "market_cap": Decimal(25_000),
                "liquidity_usd": Decimal(8_000),
                "volume_24h": Decimal(50_000),
                "trading_status": TradingStatus.TRADING,
                "provider": "dexscreener",
            }
        )

        closed = await service.review(now=NOW + timedelta(minutes=2))
        await db_session.commit()

        assert closed.closed >= 1
        assert closed.audited >= 1
        audits = (
            await db_session.scalars(
                select(PaperShadowTradeAudit).where(PaperShadowTradeAudit.mint_address == mint)
            )
        ).all()
        assert len(audits) == closed.audited
        assert PaperShadowTradeAudit.__table__.columns.get("manual_action_at") is None

    async def test_transaction_scoped_paper_review_lock_coalesces_overlap(
        self, test_session_factory
    ) -> None:
        """Only one complete paper review may run at a time."""
        async with test_session_factory() as first:
            assert await acquire_paper_review_lock(first) is True

            async with test_session_factory() as second:
                assert await acquire_paper_review_lock(second) is False
                await second.rollback()

            await first.rollback()

        async with test_session_factory() as after_release:
            assert await acquire_paper_review_lock(after_release) is True
            await after_release.rollback()

    async def test_scheduler_coalesces_overlapping_paper_reviews(
        self, test_session_factory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A concurrent scheduler pass skips instead of entering review logic."""

        class _Outcome:
            def as_dict(self) -> dict[str, int]:
                return {"opened": 0, "closed": 0}

        first_review_entered = asyncio.Event()
        release_first_review = asyncio.Event()
        paper_reviews = 0
        shadow_reviews = 0

        class _PaperWalletService:
            def __init__(self, session: AsyncSession) -> None:
                self._session = session

            async def review(self, *, now: datetime) -> _Outcome:
                nonlocal paper_reviews
                paper_reviews += 1
                first_review_entered.set()
                await release_first_review.wait()
                return _Outcome()

        class _ShadowPaperService:
            def __init__(self, session: AsyncSession) -> None:
                self._session = session

            async def review(self, *, now: datetime) -> _Outcome:
                nonlocal shadow_reviews
                shadow_reviews += 1
                return _Outcome()

        async def _publish_live_update(event_type: str, **kwargs: object) -> int:
            assert event_type == "paper.changed"
            return 0

        monkeypatch.setattr(settings, "FEATURE_PAPER_WALLET_ENABLED", True)
        monkeypatch.setattr(paper_scheduler, "SessionFactory", test_session_factory)
        monkeypatch.setattr(paper_scheduler, "PaperWalletService", _PaperWalletService)
        monkeypatch.setattr(paper_scheduler, "ShadowPaperService", _ShadowPaperService)
        monkeypatch.setattr(paper_scheduler, "publish_live_update", _publish_live_update)

        first = asyncio.create_task(paper_scheduler._paper_review())
        await first_review_entered.wait()

        second = await paper_scheduler._paper_review()
        assert second == {"skipped": "review_already_running"}
        assert paper_reviews == 1
        assert shadow_reviews == 0

        release_first_review.set()
        first_result = await first

        assert first_result == {
            "opened": 0,
            "closed": 0,
            "shadow": {"opened": 0, "closed": 0},
        }
        assert paper_reviews == 1
        assert shadow_reviews == 1
