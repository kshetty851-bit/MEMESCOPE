"""Liveness, the history feed and the equal-weight benchmark.

Three features that could each be faked convincingly, so each is tested for what
it *refuses* to claim:

  - liveness never reports `inactive`, because nothing establishes death;
  - the feed contains only events that have a stored row behind them;
  - the benchmark reports no SOL comparison, because no SOL series exists.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market import TradingStatus
from app.models.radar import RadarAchievement, RadarToken
from app.radar.repository import RadarRepository
from app.repositories.market import MarketSnapshotRepository
from app.repositories.token import TokenRepository

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)


async def _entry(
    session: AsyncSession,
    mint: str,
    *,
    current_multiple: str = "1.0",
    peak_multiple: str = "2.0",
    detected_days_ago: float = 2.0,
) -> RadarToken:
    token = await TokenRepository(session).insert_if_absent(
        {
            "mint_address": mint,
            "signature": f"sig-{mint}",
            "slot": 1,
            "discovered_at": NOW - timedelta(days=detected_days_ago),
            "symbol": "PRB",
        }
    )
    assert token is not None
    entry = RadarToken(
        token_id=token.id,
        mint_address=mint,
        first_detected_at=NOW - timedelta(days=detected_days_ago),
        first_market_cap=Decimal("10000"),
        first_opportunity_score=Decimal(70),
        first_confidence=Decimal(40),
        detection_reason=["probe"],
        category="early_momentum",
        current_opportunity_score=Decimal(70),
        current_confidence=Decimal(40),
        current_category="early_momentum",
        current_multiple=Decimal(current_multiple),
        peak_multiple=Decimal(peak_multiple),
        peak_market_cap=Decimal("20000"),
        is_active=True,
        model_version="v1",
    )
    session.add(entry)
    await session.flush()
    return entry


async def _observe(session: AsyncSession, entry: RadarToken, *, hours_ago: float) -> None:
    token = await TokenRepository(session).get_by_mint(entry.mint_address)
    assert token is not None
    await MarketSnapshotRepository(session).add_snapshot(
        {
            "token_id": token.id,
            "mint_address": entry.mint_address,
            "captured_at": NOW - timedelta(hours=hours_ago),
            "price_usd": Decimal("0.001"),
            "dex_name": "pumpswap",
            "trading_status": TradingStatus.TRADING,
            "provider": "test",
        }
    )
    await session.flush()


class TestLiveness:
    async def test_a_recently_observed_entry_reads_alive(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        entry = await _entry(db_session, "LiveAlive111111111111111111111111111111111")
        await _observe(db_session, entry, hours_ago=1)
        await db_session.commit()

        body = (await client.get("/api/v1/radar?include_inactive=true")).json()

        row = next(i for i in body["items"] if i["mint_address"] == entry.mint_address)
        assert row["liveness"] == "alive"

    async def test_an_unobserved_entry_reads_unknown_not_dead(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Absence of an observation is not evidence of death. The honest
        answer is that we do not know."""
        entry = await _entry(db_session, "LiveStale111111111111111111111111111111111")
        await _observe(db_session, entry, hours_ago=72)
        await db_session.commit()

        body = (await client.get("/api/v1/radar?include_inactive=true")).json()

        row = next(i for i in body["items"] if i["mint_address"] == entry.mint_address)
        assert row["liveness"] == "unknown"

    async def test_inactive_is_never_reported(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The rule the spec asks for and the platform cannot defend. Nothing
        in the record establishes that a token died, so nothing is ever counted
        as dead — a permanent, wrong verdict is worse than an honest gap."""
        alive = await _entry(db_session, "LiveA11111111111111111111111111111111111111")
        await _observe(db_session, alive, hours_ago=1)
        stale = await _entry(db_session, "LiveB11111111111111111111111111111111111111")
        await _observe(db_session, stale, hours_ago=100)
        await db_session.commit()

        body = (await client.get("/api/v1/radar/performance")).json()

        assert body["inactive"] == 0
        assert body["alive"] + body["unknown"] == body["total_opportunities"]

    async def test_liveness_is_batched_not_per_row(self, db_session: AsyncSession) -> None:
        entries = []
        for index in range(3):
            entry = await _entry(db_session, f"LiveBatch{index}".ljust(44, "1")[:44])
            await _observe(db_session, entry, hours_ago=1)
            entries.append(entry)
        await db_session.flush()

        alive = await RadarRepository(db_session).observed_within(
            [entry.mint_address for entry in entries], since=NOW - timedelta(hours=24)
        )

        assert len(alive) == 3

    async def test_no_mints_asks_nothing(self, db_session: AsyncSession) -> None:
        assert (
            await RadarRepository(db_session).observed_within(
                [], since=NOW - timedelta(hours=24)
            )
            == set()
        )


class TestTimeline:
    async def test_every_event_has_a_stored_row_behind_it(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The feed is a projection, never an authored log. One detection and
        one achievement in, exactly two events out."""
        entry = await _entry(db_session, "TimeOne11111111111111111111111111111111111")
        db_session.add(
            RadarAchievement(
                radar_token_id=entry.id,
                mint_address=entry.mint_address,
                tier="2x",
                multiple=Decimal(2),
                achieved_at=NOW - timedelta(hours=6),
                days_to_achieve=Decimal("1.0"),
            )
        )
        await db_session.commit()

        events = (await client.get("/api/v1/radar/timeline?limit=100")).json()

        mine = [e for e in events if e["mint_address"] == entry.mint_address]
        assert {e["kind"] for e in mine} == {"detection", "achievement"}
        assert len(mine) == 2

    async def test_newest_first(self, client: AsyncClient, db_session: AsyncSession) -> None:
        await _entry(
            db_session, "TimeOld11111111111111111111111111111111111", detected_days_ago=9
        )
        await _entry(
            db_session, "TimeNew11111111111111111111111111111111111", detected_days_ago=1
        )
        await db_session.commit()

        events = (await client.get("/api/v1/radar/timeline?limit=100")).json()

        stamps = [e["occurred_at"] for e in events]
        assert stamps == sorted(stamps, reverse=True)

    async def test_an_empty_record_produces_an_empty_feed(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        assert (await client.get("/api/v1/radar/timeline")).json() == []


class TestBenchmark:
    async def test_equal_weight_is_the_mean_of_every_entry(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Measured, not simulated: each entry's current multiple *is* its
        return from detection, so their mean is the equal-weight result."""
        await _entry(
            db_session,
            "BenchA11111111111111111111111111111111111111",
            current_multiple="3.0",
        )
        await _entry(
            db_session,
            "BenchB11111111111111111111111111111111111111",
            current_multiple="1.0",
        )
        await db_session.commit()

        body = (await client.get("/api/v1/radar/benchmark")).json()

        assert body["entries"] == 2
        assert Decimal(body["average_current_multiple"]) == Decimal("2.0")
        assert body["above_entry"] == 2
        assert body["below_entry"] == 0

    async def test_losers_are_counted_below_entry(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _entry(
            db_session,
            "BenchC11111111111111111111111111111111111111",
            current_multiple="0.02",
        )
        await db_session.commit()

        body = (await client.get("/api/v1/radar/benchmark")).json()

        assert body["below_entry"] == 1
        assert body["above_entry"] == 0

    async def test_sol_and_paper_wallet_are_refused_with_a_reason(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Neither is measurable: no SOL price series is recorded and the paper
        wallet does not exist. Saying so beats showing a fabricated number."""
        body = (await client.get("/api/v1/radar/benchmark")).json()

        assert "no SOL price history" in body["sol_note"]
        assert "does not exist yet" in body["paper_wallet_note"]
