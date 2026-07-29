"""Radar persistence guarantees, against a real database.

The engine's correctness is covered by unit tests. What needs a database is the
set of promises the track record rests on:

* first detection is written **once** and never rewritten;
* the peak only ever rises;
* achievements are permanent and never duplicated;
* a token that stops qualifying keeps its row, its history and its milestones.

Those are the properties that make the record evidence rather than marketing,
and every one of them is a write-path concern.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market import TokenMarketSnapshot
from app.models.radar import RadarAchievement, RadarSnapshot
from app.models.token import DiscoveredToken
from app.radar.repository import RadarRepository
from app.radar.service import RadarService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


async def _seed_token(session: AsyncSession, mint: str) -> DiscoveredToken:
    # `signature` and `slot` are NOT NULL: the scanner always knows the
    # transaction and slot that created a mint, so both are required rather
    # than optional. A fixture that omits them fails at the database, not in
    # the code under test.
    token = DiscoveredToken(
        mint_address=mint,
        name="Radar Probe",
        symbol="RDR",
        signature=f"sig-{uuid.uuid4()}",
        slot=1,
    )
    session.add(token)
    await session.flush()
    return token


async def _seed_series(
    session: AsyncSession,
    token: DiscoveredToken,
    *,
    count: int = 48,
    price: Decimal = Decimal("0.001"),
    price_step: Decimal = Decimal("0.00004"),
    liquidity: Decimal = Decimal(25_000),
    liquidity_step: Decimal = Decimal(300),
) -> None:
    for index in range(count):
        session.add(
            TokenMarketSnapshot(
                token_id=token.id,
                mint_address=token.mint_address,
                captured_at=NOW - timedelta(minutes=(count - index) * 30),
                price_usd=price + price_step * Decimal(index),
                market_cap=Decimal(150_000),
                liquidity_usd=liquidity + liquidity_step * Decimal(index),
                volume_24h=Decimal(30_000) + Decimal(index) * 400,
                volume_1h=Decimal(1_500),
                buy_count_24h=180,
                sell_count_24h=70,
                provider="test",
            )
        )
    await session.flush()


class TestFirstDetectionIsImmutable:
    async def test_detection_records_the_first_block(self, db_session: AsyncSession) -> None:
        token = await _seed_token(db_session, "RadarMintImmutable0000000000000000000001")
        await _seed_series(db_session, token)

        assert await RadarService(db_session).evaluate_mint(token.mint_address, now=NOW)

        entry = await RadarRepository(db_session).get(token.mint_address)
        assert entry is not None
        assert entry.first_price is not None
        assert entry.first_opportunity_score > 0
        assert entry.detection_reason != []

    async def test_re_evaluation_never_rewrites_the_first_block(
        self, db_session: AsyncSession
    ) -> None:
        # The guarantee every reported return depends on. If a later evaluation
        # could reset first_price, the platform would silently improve its own
        # track record each time it re-detected a token.
        token = await _seed_token(db_session, "RadarMintImmutable0000000000000000000002")
        await _seed_series(db_session, token)
        service = RadarService(db_session)

        await service.evaluate_mint(token.mint_address, now=NOW)
        repository = RadarRepository(db_session)
        original = await repository.get(token.mint_address)
        assert original is not None
        first_price = original.first_price
        first_score = original.first_opportunity_score
        detected_at = original.first_detected_at

        # A later, much higher-priced observation.
        db_session.add(
            TokenMarketSnapshot(
                token_id=token.id,
                mint_address=token.mint_address,
                captured_at=NOW + timedelta(hours=2),
                price_usd=Decimal("0.5"),
                market_cap=Decimal(900_000),
                liquidity_usd=Decimal(80_000),
                volume_24h=Decimal(120_000),
                buy_count_24h=400,
                sell_count_24h=90,
                provider="test",
            )
        )
        await db_session.flush()
        await service.evaluate_mint(token.mint_address, now=NOW + timedelta(hours=2))

        refreshed = await repository.get(token.mint_address)
        assert refreshed is not None
        assert refreshed.first_price == first_price
        assert refreshed.first_opportunity_score == first_score
        assert refreshed.first_detected_at == detected_at
        # …while the current state did move.
        assert refreshed.current_price == Decimal("0.5")


class TestPeakIsMonotonic:
    async def test_peak_rises_and_never_falls_back(self, db_session: AsyncSession) -> None:
        token = await _seed_token(db_session, "RadarMintPeak000000000000000000000000001")
        await _seed_series(db_session, token)
        service = RadarService(db_session)
        repository = RadarRepository(db_session)

        await service.evaluate_mint(token.mint_address, now=NOW)

        # Spike, then crash.
        for offset, price in ((2, Decimal("0.05")), (4, Decimal("0.0001"))):
            db_session.add(
                TokenMarketSnapshot(
                    token_id=token.id,
                    mint_address=token.mint_address,
                    captured_at=NOW + timedelta(hours=offset),
                    price_usd=price,
                    market_cap=Decimal(200_000),
                    liquidity_usd=Decimal(30_000),
                    volume_24h=Decimal(40_000),
                    buy_count_24h=150,
                    sell_count_24h=100,
                    provider="test",
                )
            )
            await db_session.flush()
            await service.evaluate_mint(token.mint_address, now=NOW + timedelta(hours=offset))

        entry = await repository.get(token.mint_address)
        assert entry is not None
        # The high genuinely happened; a later crash must not erase it.
        assert entry.peak_price == Decimal("0.05")
        assert entry.current_price == Decimal("0.0001")
        assert entry.peak_multiple is not None
        assert entry.current_multiple is not None
        assert entry.peak_multiple > entry.current_multiple


class TestAchievementsArePermanent:
    async def test_milestones_are_awarded_from_peak_and_never_duplicated(
        self, db_session: AsyncSession
    ) -> None:
        token = await _seed_token(db_session, "RadarMintAchieve00000000000000000000001")
        await _seed_series(db_session, token)
        service = RadarService(db_session)

        await service.evaluate_mint(token.mint_address, now=NOW)
        entry = await RadarRepository(db_session).get(token.mint_address)
        assert entry is not None
        first_price = entry.first_price
        assert first_price is not None

        # A 12x from detection, then a collapse.
        db_session.add(
            TokenMarketSnapshot(
                token_id=token.id,
                mint_address=token.mint_address,
                captured_at=NOW + timedelta(hours=1),
                price_usd=first_price * Decimal(12),
                market_cap=Decimal(2_000_000),
                liquidity_usd=Decimal(90_000),
                volume_24h=Decimal(300_000),
                buy_count_24h=500,
                sell_count_24h=120,
                provider="test",
            )
        )
        await db_session.flush()
        await service.evaluate_mint(token.mint_address, now=NOW + timedelta(hours=1))

        earned = (
            await db_session.scalars(
                select(RadarAchievement.tier).where(
                    RadarAchievement.mint_address == token.mint_address
                )
            )
        ).all()
        assert sorted(earned) == sorted(["2x", "5x", "10x"])

        # Evaluating again must not duplicate them.
        await service.evaluate_mint(token.mint_address, now=NOW + timedelta(hours=2))
        again = (
            await db_session.scalars(
                select(RadarAchievement.tier).where(
                    RadarAchievement.mint_address == token.mint_address
                )
            )
        ).all()
        assert len(again) == len(earned)


class TestRecordIsNeverPruned:
    async def test_a_failing_token_keeps_its_row_and_history(
        self, db_session: AsyncSession
    ) -> None:
        # Transparency is the feature. A track record that quietly drops its
        # losers is marketing, not evidence.
        token = await _seed_token(db_session, "RadarMintKept0000000000000000000000001")
        await _seed_series(db_session, token)
        service = RadarService(db_session)
        repository = RadarRepository(db_session)

        await service.evaluate_mint(token.mint_address, now=NOW)

        # Collapse: liquidity gone, price near zero.
        db_session.add(
            TokenMarketSnapshot(
                token_id=token.id,
                mint_address=token.mint_address,
                captured_at=NOW + timedelta(hours=3),
                price_usd=Decimal("0.0000001"),
                market_cap=Decimal(500),
                liquidity_usd=Decimal(100),
                volume_24h=Decimal(50),
                buy_count_24h=1,
                sell_count_24h=90,
                provider="test",
            )
        )
        await db_session.flush()
        await service.evaluate_mint(token.mint_address, now=NOW + timedelta(hours=3))
        await db_session.flush()

        entry = await repository.get(token.mint_address)
        assert entry is not None, "a failed opportunity must stay on the record"
        history = await repository.snapshots(token.mint_address)
        assert len(history) >= 1


class TestSnapshotMateriality:
    async def test_an_unchanged_token_does_not_write_a_row_every_cycle(
        self, db_session: AsyncSession
    ) -> None:
        # Without this the timeline becomes thousands of identical rows a day
        # and stops being readable — the same reason token_score_history has a
        # materiality rule.
        token = await _seed_token(db_session, "RadarMintMaterial000000000000000000001")
        await _seed_series(db_session, token)
        service = RadarService(db_session)

        await service.evaluate_mint(token.mint_address, now=NOW)
        await db_session.flush()
        await service.evaluate_mint(token.mint_address, now=NOW + timedelta(minutes=15))
        await db_session.flush()
        await service.evaluate_mint(token.mint_address, now=NOW + timedelta(minutes=30))
        # The test session runs with `autoflush=False`, so pending ORM inserts
        # are not visible to a later SELECT until flushed. Production flushes on
        # commit at the end of each sweep; here it has to be explicit, or the
        # materiality rule would appear to work simply because nothing was
        # written at all.
        await db_session.flush()

        rows = (
            await db_session.scalars(
                select(RadarSnapshot).where(RadarSnapshot.mint_address == token.mint_address)
            )
        ).all()
        assert len(rows) == 1


class TestSweepIsAdditive:
    async def test_sweep_never_touches_existing_scoring_tables(
        self, db_session: AsyncSession
    ) -> None:
        # The Radar is a new layer, not a replacement. Nothing it does may
        # disturb the launch scanner's pipeline.
        token = await _seed_token(db_session, "RadarMintAdditive000000000000000000001")
        await _seed_series(db_session, token)

        before = await db_session.scalar(select(TokenMarketSnapshot.id).limit(1))
        await RadarService(db_session).evaluate_mint(token.mint_address, now=NOW)
        after = await db_session.scalar(select(TokenMarketSnapshot.id).limit(1))

        assert before == after
