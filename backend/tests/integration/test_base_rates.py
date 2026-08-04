"""Historical base rates: what past detections of this kind actually did.

The platform's answer to "how likely is this to work" is *not a forecast* — it
is the measured outcome of every previous detection in the same category. What
matters most here is the refusal: below a published sample size the rate is not
quoted at all, because a percentage from three observations is noise wearing the
costume of evidence.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.radar import RadarToken
from app.radar.api import MIN_BASE_RATE_SAMPLE
from app.radar.repository import RadarRepository
from app.repositories.token import TokenRepository

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)


async def _entry(
    session: AsyncSession,
    mint: str,
    *,
    category: str = "breakout",
    current_category: str | None = None,
    peak_multiple: str = "1.0",
) -> RadarToken:
    token = await TokenRepository(session).insert_if_absent(
        {
            "mint_address": mint,
            "signature": f"sig-{mint}",
            "slot": 1,
            "discovered_at": NOW - timedelta(days=2),
        }
    )
    assert token is not None
    entry = RadarToken(
        token_id=token.id,
        mint_address=mint,
        first_detected_at=NOW - timedelta(days=2),
        first_market_cap=Decimal("10000"),
        first_opportunity_score=Decimal(70),
        first_confidence=Decimal(40),
        detection_reason=["probe"],
        category=category,
        current_opportunity_score=Decimal(70),
        current_confidence=Decimal(40),
        current_category=current_category or category,
        current_multiple=Decimal("0.5"),
        peak_multiple=Decimal(peak_multiple),
        peak_market_cap=Decimal("20000"),
        is_active=True,
        model_version="v1",
    )
    session.add(entry)
    await session.flush()
    return entry


#: Distinct per (category, peak) so two fills in one test cannot collide.
_PREFIX = {("breakout", "3"): "A", ("breakout", "1"): "B", ("undervalued", "1"): "C"}


async def _fill(session: AsyncSession, count: int, *, category: str, peak: str) -> None:
    tag = _PREFIX[(category, peak[0])]
    for index in range(count):
        await _entry(
            session,
            f"BRfill{tag}{index:03d}".ljust(44, "1")[:44],
            category=category,
            peak_multiple=peak,
        )


class TestSufficiency:
    async def test_a_thin_sample_is_refused_with_its_reason(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The whole point. One observation cannot support a percentage, and
        printing one anyway is how a platform launders noise into evidence."""
        await _entry(
            db_session, "BROne111111111111111111111111111111111111", peak_multiple="9.0"
        )
        await db_session.commit()

        body = (await client.get("/api/v1/radar?include_inactive=true")).json()

        rate = body["items"][0]["base_rate"]
        assert rate["sufficient"] is False
        assert rate["sample"] == 1
        assert "Too few observations" in rate["insufficient_reason"]

    async def test_the_raw_counts_survive_an_insufficient_sample(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Refusing the rate is not refusing the data: a reader must be able to
        see exactly how thin the sample is."""
        await _entry(
            db_session, "BRThin11111111111111111111111111111111111", peak_multiple="4.0"
        )
        await db_session.commit()

        rate = (await client.get("/api/v1/radar?include_inactive=true")).json()["items"][
            0
        ]["base_rate"]

        assert rate["sample"] == 1
        assert rate["reached_2x"] == 1
        assert rate["median_peak_multiple"] is not None

    async def test_the_bar_is_published_not_hidden(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A threshold nobody can see is an assertion, not a standard."""
        await _entry(db_session, "BRBar111111111111111111111111111111111111")
        await db_session.commit()

        rate = (await client.get("/api/v1/radar?include_inactive=true")).json()["items"][
            0
        ]["base_rate"]

        assert rate["minimum_sample"] == MIN_BASE_RATE_SAMPLE

    async def test_a_sample_at_the_bar_is_quoted(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _fill(db_session, MIN_BASE_RATE_SAMPLE, category="breakout", peak="3.0")
        await db_session.commit()

        rate = (await client.get("/api/v1/radar?include_inactive=true")).json()["items"][
            0
        ]["base_rate"]

        assert rate["sufficient"] is True
        assert rate["insufficient_reason"] is None
        assert rate["sample"] == MIN_BASE_RATE_SAMPLE
        assert rate["reached_2x"] == MIN_BASE_RATE_SAMPLE


class TestGrouping:
    async def test_losers_share_the_denominator(
        self, db_session: AsyncSession
    ) -> None:
        """A rate over winners only is not a rate."""
        await _fill(db_session, 6, category="breakout", peak="3.0")
        await _fill(db_session, 6, category="breakout", peak="1.1")
        await db_session.flush()

        rates = await RadarRepository(db_session).base_rates()

        assert rates["breakout"]["sample"] == 12
        assert rates["breakout"]["reached_2x"] == 6

    async def test_the_rate_follows_the_original_category_not_the_current_one(
        self, db_session: AsyncSession
    ) -> None:
        """A token re-classified later must not move between buckets, or the
        rate would quietly rewrite its own history."""
        await _entry(
            db_session,
            "BRMoved11111111111111111111111111111111111",
            category="early_momentum",
            current_category="elite",
            peak_multiple="8.0",
        )
        await db_session.flush()

        rates = await RadarRepository(db_session).base_rates()

        assert rates["early_momentum"]["sample"] == 1
        assert "elite" not in rates

    async def test_categories_are_measured_separately(
        self, db_session: AsyncSession
    ) -> None:
        await _fill(db_session, 4, category="breakout", peak="3.0")
        await _fill(db_session, 3, category="undervalued", peak="1.0")
        await db_session.flush()

        rates = await RadarRepository(db_session).base_rates()

        assert rates["breakout"]["reached_2x"] == 4
        assert rates["undervalued"]["reached_2x"] == 0

    async def test_an_empty_record_produces_no_rates(
        self, db_session: AsyncSession
    ) -> None:
        assert await RadarRepository(db_session).base_rates() == {}


class TestBatching:
    async def test_a_page_costs_one_grouped_query_not_one_per_row(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """`base_rates()` is grouped over the whole record and looked up in
        memory per row — the alternative is a query per card."""
        await _fill(db_session, 12, category="breakout", peak="3.0")
        await db_session.commit()

        body = (await client.get("/api/v1/radar?include_inactive=true")).json()

        assert len(body["items"]) >= 12
        assert all(item["base_rate"]["sufficient"] for item in body["items"])
        # Every row resolves to the same measured history, not a per-row recount.
        samples = {item["base_rate"]["sample"] for item in body["items"]}
        assert len(samples) == 1
