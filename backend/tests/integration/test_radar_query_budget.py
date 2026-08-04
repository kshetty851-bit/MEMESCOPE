"""The Radar page costs a fixed number of queries, whatever its size.

Sprint 24. Latency benchmarks catch an N+1 only once the table is large enough
to hurt, and by then it is in production. Counting statements catches it on the
first row, and — more usefully — states the budget as a number a reviewer can
argue with.

The property asserted is not "under N milliseconds". It is that **serving ten
rows and serving one row issue the same number of statements**: the page is
resolved in batches, and nothing walks the result set.

This guards the whole Sprint 23/24 read path — market context, latest
snapshots, live signals and the readout layer — which between them added six
lookups and must never add a seventh per row.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.radar import RadarSnapshot, RadarToken
from app.repositories.token import TokenRepository

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)


class Counter:
    """Counts statements on the connection the request will actually use."""

    def __init__(self) -> None:
        self.count = 0

    def __call__(self, *args: object, **kwargs: object) -> None:
        self.count += 1


async def _seed(session: AsyncSession, index: int) -> None:
    mint = f"QueryBudget{index:032d}"
    token = await TokenRepository(session).insert_if_absent(
        {
            "mint_address": mint,
            "signature": f"sig-{mint}",
            "slot": 1,
            "discovered_at": NOW - timedelta(hours=6),
            "block_time": NOW - timedelta(hours=6),
            "symbol": f"QB{index}",
        }
    )
    assert token is not None
    entry = RadarToken(
        token_id=token.id,
        mint_address=mint,
        first_detected_at=NOW - timedelta(days=1),
        first_market_cap=Decimal("10000"),
        first_opportunity_score=Decimal(70),
        first_confidence=Decimal(40),
        detection_reason=["volume_expanding", "trend_aligned"],
        category="early_momentum",
        current_opportunity_score=Decimal(90 - index),
        current_confidence=Decimal(40),
        current_category="early_momentum",
        current_multiple=Decimal("1.1"),
        peak_multiple=Decimal("1.2"),
        is_active=True,
        model_version="v1",
    )
    session.add(entry)
    await session.flush()
    session.add(
        RadarSnapshot(
            radar_token_id=entry.id,
            mint_address=mint,
            captured_at=NOW,
            opportunity_score=Decimal(70),
            confidence=Decimal(40),
            coverage=Decimal(85),
            category="early_momentum",
            dimensions={"risk": {"score": "80", "available": True, "reasons": []}},
            reasons=["volume_expanding"],
            model_version="v1",
        )
    )
    await session.flush()


async def _statements_for(
    client: AsyncClient, db_session: AsyncSession, *, page_size: int
) -> int:
    counter = Counter()
    connection = db_session.sync_session.connection()
    event.listen(connection.engine, "before_cursor_execute", counter)
    try:
        response = await client.get(f"/api/v1/radar?page_size={page_size}")
        assert response.status_code == 200
    finally:
        event.remove(connection.engine, "before_cursor_execute", counter)
    return counter.count


class TestQueryBudget:
    async def test_ten_rows_cost_what_one_row_costs(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The whole point. If this fails, something walks the result set."""
        for index in range(10):
            await _seed(db_session, index)
        await db_session.commit()

        one = await _statements_for(client, db_session, page_size=1)
        ten = await _statements_for(client, db_session, page_size=10)

        assert ten == one, (
            f"serving 10 rows issued {ten} statements against {one} for a single "
            "row — the page is no longer resolved in batches"
        )

    async def test_the_budget_is_stated_rather_than_drifting(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A ceiling, not an equality: a refactor that removes a lookup should
        not fail, and one that adds another should be argued for explicitly.

        Measured at 11: the ranking page, its count, names, tiers, liveness,
        base rates, the three market-context lookups, and the newest snapshots.
        Live-signal resolution short-circuits to one statement here because no
        opportunity is open for these mints; the ceiling leaves room for the
        second.
        """
        for index in range(10):
            await _seed(db_session, index)
        await db_session.commit()

        assert await _statements_for(client, db_session, page_size=10) <= 12

    async def test_the_readout_layer_costs_nothing(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Every why-now sentence is derived from rows the page already loaded:
        `detection_reason` and `current_multiple` sit on the entry, and the
        signal was batched with the page. Sentences are free."""
        for index in range(10):
            await _seed(db_session, index)
        await db_session.commit()

        statements = await _statements_for(client, db_session, page_size=10)
        body = (await client.get("/api/v1/radar?page_size=10")).json()

        assert len(body["items"]) == 10
        assert all(item["why_now"]["sentence"] for item in body["items"])
        assert statements <= 12
