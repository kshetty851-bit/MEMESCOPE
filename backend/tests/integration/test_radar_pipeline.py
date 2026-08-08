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
from httpx import AsyncClient
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


class TestEventDrivenRefresh:
    async def test_refresh_evaluates_only_the_changed_mint(
        self, db_session: AsyncSession
    ) -> None:
        first = await _seed_token(db_session, "RadarEventMint00000000000000000000000001")
        second = await _seed_token(db_session, "RadarEventMint00000000000000000000000002")
        await _seed_series(db_session, first)
        await _seed_series(db_session, second)

        outcome = await RadarService(db_session).refresh_mints([first.mint_address], now=NOW)

        assert outcome.evaluated == 1
        assert outcome.tracked == 1
        assert outcome.updated_mints == (first.mint_address,)
        assert await RadarRepository(db_session).get(second.mint_address) is None


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


class TestTheSweepRefreshesWhatItHasAlreadyDetected:
    """Regression cover for a Radar whose returns silently froze at detection.

    `candidate_mints` ranks by most recent observation, so it surfaces whatever
    enrichment last touched. A detected token leaves that window within minutes,
    and nothing else fed the sweep — so `current_multiple` and `peak_multiple`
    kept their detection-time values indefinitely while the price moved.

    Measured on the live database before the fix: 0 of 28 tracked entries were
    still in the candidate window, with staleness up to seven hours.
    """

    async def test_tracked_mints_returns_detected_entries_stalest_first(
        self, db_session: AsyncSession
    ) -> None:
        repository = RadarRepository(db_session)

        for index, mint in enumerate(("mint-stale", "mint-fresh")):
            token = await _seed_token(db_session, mint)
            await _seed_series(db_session, token)
            await RadarService(db_session).evaluate_mint(
                mint, now=NOW + timedelta(hours=index)
            )

        tracked = await repository.tracked_mints(limit=10)

        assert set(tracked) == {"mint-stale", "mint-fresh"}
        # Stalest first, so a truncated run degrades evenly rather than
        # stranding whichever entries happen to sort last.
        assert tracked[0] == "mint-stale"

    async def test_a_sweep_refreshes_an_entry_outside_the_candidate_window(
        self, db_session: AsyncSession
    ) -> None:
        """The exact production shape: detected, then never observed again.

        The tracked token's own series stops, while other tokens keep being
        snapshotted — so it cannot appear in `candidate_mints` and only the
        tracked population can reach it.
        """
        token = await _seed_token(db_session, "mint-tracked")
        await _seed_series(db_session, token)

        service = RadarService(db_session)
        assert await service.evaluate_mint("mint-tracked", now=NOW) is True

        repository = RadarRepository(db_session)
        entry = await repository.get("mint-tracked")
        assert entry is not None
        detected_multiple = entry.current_multiple
        detected_at = entry.last_evaluated_at

        # The price moves after detection.
        db_session.add(
            TokenMarketSnapshot(
                token_id=token.id,
                mint_address=token.mint_address,
                captured_at=NOW + timedelta(minutes=5),
                price_usd=Decimal("0.010"),
                market_cap=Decimal(900_000),
                liquidity_usd=Decimal(60_000),
                volume_24h=Decimal(90_000),
                volume_1h=Decimal(9_000),
                buy_count_24h=400,
                sell_count_24h=90,
                provider="test",
            )
        )
        # Newer, busier tokens crowd the most-recently-observed window.
        for filler in range(3):
            other = await _seed_token(db_session, f"mint-filler-{filler}")
            await _seed_series(db_session, other)
            for step in range(14):
                db_session.add(
                    TokenMarketSnapshot(
                        token_id=other.id,
                        mint_address=other.mint_address,
                        captured_at=NOW + timedelta(minutes=30 + step),
                        price_usd=Decimal("0.002"),
                        market_cap=Decimal(200_000),
                        liquidity_usd=Decimal(30_000),
                        volume_24h=Decimal(40_000),
                        volume_1h=Decimal(2_000),
                        buy_count_24h=200,
                        sell_count_24h=80,
                        provider="test",
                    )
                )
        await db_session.flush()

        later = NOW + timedelta(hours=1)
        candidates = await repository.candidate_mints(limit=3)
        assert "mint-tracked" not in candidates, (
            "fixture no longer reproduces the bug: the tracked mint must fall "
            "outside the candidate window for this test to mean anything"
        )

        await RadarService(db_session).sweep(limit=3, now=later)

        refreshed = await repository.get("mint-tracked")
        assert refreshed is not None
        assert refreshed.last_evaluated_at > detected_at
        assert refreshed.current_multiple != detected_multiple
        assert refreshed.current_price == Decimal("0.010")


class TestRadarSurfacesCarryTokenIdentity:
    """Regression cover for nameless Radar entries.

    `RadarEntryOut` declares `name` and `symbol`, and the Radar card renders
    `symbol ?? name ?? <truncated mint>`. But `radar_tokens` stores neither and
    `_to_entry` never populated them, so every Radar surface fell through to the
    mint address for every token — while `/scores/top`, which joins
    `discovered_tokens`, showed names correctly on the same tokens.

    Identity deliberately still lives only in `discovered_tokens`; duplicating
    it onto `radar_tokens` would let the two disagree.
    """

    async def test_names_for_resolves_identity_from_discovered_tokens(
        self, db_session: AsyncSession
    ) -> None:
        await _seed_token(db_session, "mint-named")
        names = await RadarRepository(db_session).names_for(["mint-named", "mint-unknown"])

        assert names["mint-named"] == ("Radar Probe", "RDR")
        # An undiscovered mint is absent rather than an empty string, so the
        # caller can fall back rather than render a blank.
        assert "mint-unknown" not in names

    async def test_names_for_is_empty_without_mints(self, db_session: AsyncSession) -> None:
        assert await RadarRepository(db_session).names_for([]) == {}

    async def test_the_radar_listing_returns_a_name(
        self, db_session: AsyncSession, client: AsyncClient
    ) -> None:
        token = await _seed_token(db_session, "mint-listed")
        await _seed_series(db_session, token)
        await RadarService(db_session).evaluate_mint("mint-listed", now=NOW)
        await db_session.commit()

        response = await client.get("/api/v1/radar", params={"page_size": 25})
        assert response.status_code == 200

        entries = {item["mint_address"]: item for item in response.json()["items"]}
        assert "mint-listed" in entries
        assert entries["mint-listed"]["name"] == "Radar Probe"
        assert entries["mint-listed"]["symbol"] == "RDR"


class TestPeakCapturesHighsBetweenSweeps:
    """Regression cover for a peak that only ever saw the latest snapshot.

    The Radar sweeps every fifteen minutes; enrichment writes snapshots as
    often as every thirty seconds. The peak was raised against `series.latest`
    alone, so a high reached between two sweeps was never recorded — even
    though the snapshot holding it was already in the database.

    Measured on the live database before the fix: 18 of 37 tracked entries
    under-reported their peak, the worst by 4.17x. It only ever errs downward,
    which flatters nothing but makes the track record wrong.
    """

    async def test_a_spike_between_sweeps_is_not_lost(self, db_session: AsyncSession) -> None:
        token = await _seed_token(db_session, "mint-spike")
        await _seed_series(db_session, token, count=20, price_step=Decimal(0))

        service = RadarService(db_session)
        assert await service.evaluate_mint("mint-spike", now=NOW) is True

        repository = RadarRepository(db_session)
        entry = await repository.get("mint-spike")
        assert entry is not None
        baseline_peak = entry.peak_multiple

        # A spike, then a full retrace — both captured by enrichment, and both
        # in the past by the time the next sweep runs.
        for index, price in enumerate([Decimal("0.005"), Decimal("0.001")]):
            db_session.add(
                TokenMarketSnapshot(
                    token_id=token.id,
                    mint_address=token.mint_address,
                    captured_at=NOW + timedelta(minutes=1 + index),
                    price_usd=price,
                    market_cap=Decimal(500_000),
                    liquidity_usd=Decimal(40_000),
                    volume_24h=Decimal(60_000),
                    volume_1h=Decimal(4_000),
                    buy_count_24h=250,
                    sell_count_24h=90,
                    provider="test",
                )
            )
        await db_session.flush()

        await service.evaluate_mint("mint-spike", now=NOW + timedelta(minutes=15))

        refreshed = await repository.get("mint-spike")
        assert refreshed is not None
        assert refreshed.peak_price == Decimal("0.005"), (
            "the spike was in the window and must have raised the peak"
        )
        assert refreshed.peak_multiple is not None
        assert refreshed.peak_multiple > baseline_peak
        # And the current reading still reflects the retrace, not the spike.
        assert refreshed.current_price == Decimal("0.001")

    async def test_the_peak_still_only_ever_rises(self, db_session: AsyncSession) -> None:
        """The monotonic guarantee the track record rests on, unchanged."""
        token = await _seed_token(db_session, "mint-monotonic")
        await _seed_series(db_session, token, count=20, price_step=Decimal(0))

        service = RadarService(db_session)
        await service.evaluate_mint("mint-monotonic", now=NOW)

        repository = RadarRepository(db_session)
        before = await repository.get("mint-monotonic")
        assert before is not None
        high_water = before.peak_price

        # Nothing but decline afterwards.
        for index in range(4):
            db_session.add(
                TokenMarketSnapshot(
                    token_id=token.id,
                    mint_address=token.mint_address,
                    captured_at=NOW + timedelta(minutes=index + 1),
                    price_usd=Decimal("0.0000001"),
                    market_cap=Decimal(100),
                    liquidity_usd=Decimal(50),
                    volume_24h=Decimal(10),
                    volume_1h=Decimal(1),
                    buy_count_24h=1,
                    sell_count_24h=90,
                    provider="test",
                )
            )
        await db_session.flush()

        await service.evaluate_mint("mint-monotonic", now=NOW + timedelta(minutes=30))

        after = await repository.get("mint-monotonic")
        assert after is not None
        assert after.peak_price == high_water


class TestRotationReachesTheWholeUniverse:
    """Regression cover for a candidate window that could not see past 1.8 minutes.

    `candidate_mints` orders by most recent observation, so on live data the
    top 500 spanned about 1.8 minutes and 22,400 of 23,355 eligible projects
    sat permanently below the cut. They were not evaluated slowly — they could
    never be evaluated at all, however good they were.
    """

    async def test_every_eligible_mint_belongs_to_exactly_one_bucket(
        self, db_session: AsyncSession
    ) -> None:
        for index in range(12):
            token = await _seed_token(db_session, f"mint-rot-{index}")
            await _seed_series(db_session, token, count=14)

        repository = RadarRepository(db_session)
        buckets = 4
        seen: list[str] = []
        for bucket in range(buckets):
            seen.extend(
                await repository.rotating_mints(limit=100, bucket=bucket, buckets=buckets)
            )

        ours = [m for m in seen if m.startswith("mint-rot-")]
        # Partition: every mint appears once across a full rotation, never twice.
        assert sorted(ours) == sorted({f"mint-rot-{i}" for i in range(12)})
        assert len(ours) == len(set(ours))

    async def test_a_stale_mint_is_reachable_though_it_never_enters_the_hot_window(
        self, db_session: AsyncSession
    ) -> None:
        # One old token, then enough newer ones to bury it in the hot ordering.
        stale = await _seed_token(db_session, "mint-stale-tail")
        await _seed_series(db_session, stale, count=14)

        for index in range(6):
            fresh = await _seed_token(db_session, f"mint-fresh-{index}")
            await _seed_series(db_session, fresh, count=14)
            for step in range(14):
                db_session.add(
                    TokenMarketSnapshot(
                        token_id=fresh.id,
                        mint_address=fresh.mint_address,
                        captured_at=NOW + timedelta(minutes=step),
                        price_usd=Decimal("0.002"),
                        market_cap=Decimal(200_000),
                        liquidity_usd=Decimal(30_000),
                        volume_24h=Decimal(40_000),
                        volume_1h=Decimal(2_000),
                        buy_count_24h=200,
                        sell_count_24h=80,
                        provider="test",
                    )
                )
        await db_session.flush()

        repository = RadarRepository(db_session)

        hot = await repository.candidate_mints(limit=3)
        assert "mint-stale-tail" not in hot, (
            "fixture no longer reproduces the bug: the stale mint must be "
            "outside the hot window for this test to mean anything"
        )

        # But a full rotation must reach it.
        buckets = 4
        reachable = [
            mint
            for bucket in range(buckets)
            for mint in await repository.rotating_mints(
                limit=100, bucket=bucket, buckets=buckets
            )
        ]
        assert "mint-stale-tail" in reachable

    async def test_an_invalid_bucket_fails_loudly(self, db_session: AsyncSession) -> None:
        # A silently-skipped slice would leave part of the universe unevaluated
        # for a full rotation with no signal at all.
        repository = RadarRepository(db_session)
        with pytest.raises(ValueError):
            await repository.rotating_mints(limit=10, bucket=4, buckets=4)
        with pytest.raises(ValueError):
            await repository.rotating_mints(limit=10, bucket=0, buckets=0)
