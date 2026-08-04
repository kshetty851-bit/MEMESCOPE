"""The track record aggregates and the achievement badges behind them.

This page is the platform's evidence, so what matters here is that nothing is
quietly favourable: losers are in the same denominator as winners, a figure with
no rows behind it is `None` rather than 0, and a badge comes from the permanent
achievement row rather than from a live column that could be corrected.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.radar import RadarAchievement, RadarToken
from app.radar.repository import RadarRepository
from app.repositories.token import TokenRepository

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)


async def _entry(
    session: AsyncSession,
    mint: str,
    *,
    first_mcap: str,
    current_multiple: str,
    peak_multiple: str,
    peak_mcap: str,
    detected_days_ago: float = 2.0,
) -> RadarToken:
    token = await TokenRepository(session).insert_if_absent(
        {
            "mint_address": mint,
            "signature": f"sig-{mint}",
            "slot": 1,
            "discovered_at": NOW - timedelta(days=detected_days_ago),
        }
    )
    assert token is not None
    entry = RadarToken(
        token_id=token.id,
        mint_address=mint,
        first_detected_at=NOW - timedelta(days=detected_days_ago),
        first_market_cap=Decimal(first_mcap),
        first_opportunity_score=Decimal(70),
        first_confidence=Decimal(40),
        detection_reason=["probe"],
        category="early_momentum",
        current_opportunity_score=Decimal(70),
        current_confidence=Decimal(40),
        current_category="early_momentum",
        current_multiple=Decimal(current_multiple),
        peak_multiple=Decimal(peak_multiple),
        peak_market_cap=Decimal(peak_mcap),
        is_active=True,
        model_version="v1",
    )
    session.add(entry)
    await session.flush()
    return entry


async def _achievement(
    session: AsyncSession, entry: RadarToken, tier: str, *, days_to_achieve: str
) -> None:
    session.add(
        RadarAchievement(
            radar_token_id=entry.id,
            mint_address=entry.mint_address,
            tier=tier,
            multiple=Decimal(tier.replace("x", "")),
            achieved_at=NOW - timedelta(days=1),
            days_to_achieve=Decimal(days_to_achieve),
        )
    )
    await session.flush()


class TestAggregates:
    async def test_losers_share_the_denominator_with_winners(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A rate computed only over the entries that worked is not a rate."""
        winner = await _entry(
            db_session,
            "TrackWin1111111111111111111111111111111111",
            first_mcap="10000",
            current_multiple="3.0",
            peak_multiple="5.0",
            peak_mcap="50000",
        )
        await _achievement(db_session, winner, "2x", days_to_achieve="1.0")
        await _entry(
            db_session,
            "TrackLose111111111111111111111111111111111",
            first_mcap="10000",
            current_multiple="0.01",
            peak_multiple="1.1",
            peak_mcap="11000",
        )
        await db_session.commit()

        body = (await client.get("/api/v1/radar/performance")).json()

        assert body["total_opportunities"] == 2
        # 1 of 2, not 1 of 1 — the loser is counted.
        assert Decimal(body["success_rate"]) == Decimal("0.5")

    async def test_median_peak_and_drawdown_are_measured(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _entry(
            db_session,
            "TrackMed1111111111111111111111111111111111",
            first_mcap="10000",
            current_multiple="1.0",
            peak_multiple="4.0",
            peak_mcap="40000",
        )
        await db_session.commit()

        body = (await client.get("/api/v1/radar/performance")).json()

        assert Decimal(body["median_peak_multiple"]) == Decimal("4.0")
        # (4 - 1) / 4 = 0.75 given back from the high.
        assert Decimal(body["average_drawdown"]).quantize(Decimal("0.01")) == Decimal("0.75")

    async def test_time_to_2x_comes_from_the_achievement_not_the_peak(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Peak multiple says how far it ran, never how long it took. Only the
        achievement row records when the tier was actually crossed."""
        entry = await _entry(
            db_session,
            "TrackTime111111111111111111111111111111111",
            first_mcap="10000",
            current_multiple="1.0",
            peak_multiple="9.0",
            peak_mcap="90000",
        )
        await _achievement(db_session, entry, "2x", days_to_achieve="0.5")
        await db_session.commit()

        body = (await client.get("/api/v1/radar/performance")).json()

        assert Decimal(body["average_days_to_2x"]) == Decimal("0.5")

    async def test_largest_peak_market_cap_is_the_maximum_ever_reached(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _entry(
            db_session,
            "TrackBig1111111111111111111111111111111111",
            first_mcap="10000",
            current_multiple="0.1",
            peak_multiple="8.0",
            peak_mcap="800000",
        )
        await _entry(
            db_session,
            "TrackSml1111111111111111111111111111111111",
            first_mcap="10000",
            current_multiple="0.1",
            peak_multiple="2.0",
            peak_mcap="20000",
        )
        await db_session.commit()

        body = (await client.get("/api/v1/radar/performance")).json()

        assert Decimal(body["largest_peak_market_cap"]) == Decimal("800000")

    async def test_an_empty_record_reports_absent_not_zero(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """ "We have not measured this" and "this is zero" are different claims,
        and a track record that confuses them is not evidence."""
        body = (await client.get("/api/v1/radar/performance")).json()

        assert body["total_opportunities"] == 0
        assert body["median_peak_multiple"] is None
        assert body["average_days_to_2x"] is None
        assert body["largest_peak_market_cap"] is None


class TestBadges:
    async def test_tiers_come_from_the_permanent_achievement_row(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Badges are read from `radar_achievements`, not recomputed from
        `peak_multiple`, so a badge once earned survives a later correction to
        the peak — and the badge can never disagree with the tier counts."""
        entry = await _entry(
            db_session,
            "TrackBadge11111111111111111111111111111111",
            first_mcap="10000",
            current_multiple="0.3",
            peak_multiple="6.0",
            peak_mcap="60000",
        )
        await _achievement(db_session, entry, "2x", days_to_achieve="1.0")
        await _achievement(db_session, entry, "5x", days_to_achieve="2.0")
        await db_session.commit()

        body = (await client.get("/api/v1/radar?include_inactive=true")).json()

        row = next(
            item for item in body["items"] if item["mint_address"] == entry.mint_address
        )
        assert row["achieved_tiers"] == ["2x", "5x"]

    async def test_an_entry_with_no_achievements_has_no_badges(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        entry = await _entry(
            db_session,
            "TrackNone111111111111111111111111111111111",
            first_mcap="10000",
            current_multiple="0.02",
            peak_multiple="1.2",
            peak_mcap="12000",
        )
        await db_session.commit()

        body = (await client.get("/api/v1/radar?include_inactive=true")).json()

        row = next(
            item for item in body["items"] if item["mint_address"] == entry.mint_address
        )
        assert row["achieved_tiers"] == []

    async def test_peak_market_cap_is_exposed_beside_the_multiple(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A multiple alone hides the scale it moved at: 5x from $4K and 5x from
        $4M are not the same call."""
        entry = await _entry(
            db_session,
            "TrackMcap111111111111111111111111111111111",
            first_mcap="18000",
            current_multiple="5.66",
            peak_multiple="34.4",
            peak_mcap="620000",
        )
        await db_session.commit()

        body = (await client.get("/api/v1/radar?include_inactive=true")).json()

        row = next(
            item for item in body["items"] if item["mint_address"] == entry.mint_address
        )
        assert Decimal(row["peak_market_cap"]) == Decimal("620000")
        assert Decimal(row["first_market_cap"]) == Decimal("18000")


class TestBatching:
    async def test_tiers_resolve_for_a_page_in_one_query(
        self, db_session: AsyncSession
    ) -> None:
        entries = []
        for index in range(3):
            entry = await _entry(
                db_session,
                f"TrackBatch{index}".ljust(44, "1")[:44],
                first_mcap="10000",
                current_multiple="1.0",
                peak_multiple="2.5",
                peak_mcap="25000",
            )
            await _achievement(db_session, entry, "2x", days_to_achieve="1.0")
            entries.append(entry)
        await db_session.flush()

        tiers = await RadarRepository(db_session).tiers_for(
            [entry.mint_address for entry in entries]
        )

        assert len(tiers) == 3
        assert all(value == ["2x"] for value in tiers.values())

    async def test_no_mints_asks_nothing(self, db_session: AsyncSession) -> None:
        assert await RadarRepository(db_session).tiers_for([]) == {}
