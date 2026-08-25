"""The universe candidate query — the wallet's admission gate, in SQL.

Every bound is asserted against a real database rather than a stub, because
each one exists to keep a specific row out of a money path and a predicate
that silently stops filtering looks identical from the outside.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market import TokenMarketSnapshot, TradingStatus
from app.models.research_data import JupiterUniverseSnapshot
from app.models.token import DiscoveredToken
from app.paper.repository import PaperRepository
from app.universe import rules
from app.universe.enrolment import SOURCE_PROGRAM

NOW = datetime.now(UTC)


async def _seed(
    session: AsyncSession,
    label: str,
    *,
    age_days: int = 40,
    liquidity: Decimal = Decimal("900000"),
    snapshot_age_s: int = 60,
    price: Decimal = Decimal("1.5"),
    status: TradingStatus = TradingStatus.TRADING,
    market_cap: Decimal | None = None,
    reference_mcap: Decimal | None = None,
    source: str = SOURCE_PROGRAM,
) -> str:
    mint = f"U{label}{uuid.uuid4().hex}"[:44]
    token = DiscoveredToken(
        mint_address=mint,
        signature=f"universe:{mint}",
        slot=0,
        source_program=source,
        block_time=NOW - timedelta(days=age_days),
        symbol=label,
    )
    session.add(token)
    await session.flush()
    session.add(
        TokenMarketSnapshot(
            token_id=token.id,
            mint_address=mint,
            captured_at=NOW - timedelta(seconds=snapshot_age_s),
            price_usd=price,
            liquidity_usd=liquidity,
            market_cap=market_cap,
            trading_status=status,
            suspect=False,
            provider="dexscreener",
        )
    )
    if reference_mcap is not None:
        session.add(
            JupiterUniverseSnapshot(
                snapshot_date=NOW.date(),
                mint_address=mint,
                fetched_at=NOW,
                symbol=label,
                market_cap=reference_mcap,
            )
        )
    await session.flush()
    return mint


async def _candidates(session: AsyncSession) -> set[str]:
    rows = await PaperRepository(session).universe_candidates(
        limit=200,
        as_of=NOW,
        min_liquidity=rules.MIN_LIQUIDITY_USD,
        min_age_days=rules.MIN_AGE_DAYS,
        freshness_seconds=rules.MAX_SNAPSHOT_AGE_SECONDS,
    )
    return {token.symbol for token, _snapshot in rows if token.symbol}


class TestTheBoundsAreEnforcedInSql:
    async def test_only_the_qualifying_row_is_returned(
        self, db_session: AsyncSession
    ) -> None:
        await _seed(db_session, "OK")
        await _seed(db_session, "YOUNG", age_days=3)
        await _seed(db_session, "SHALLOW", liquidity=Decimal("1000"))
        await _seed(db_session, "STALE", snapshot_age_s=4000)
        await _seed(db_session, "HALTED", status=TradingStatus.INACTIVE)
        await _seed(db_session, "SCANNER", source="pump_fun")

        assert await _candidates(db_session) == {"OK"}


class TestTheCrossSourceCheck:
    async def test_a_venue_price_the_provider_contradicts_is_refused(
        self, db_session: AsyncSession
    ) -> None:
        """The real JUP/MET failure: $3.64T implied against $676M reported."""
        await _seed(
            db_session,
            "MISPRICED",
            market_cap=Decimal("3638711318036"),
            reference_mcap=Decimal("676435795"),
        )
        assert await _candidates(db_session) == set()

    async def test_an_ordinary_disagreement_still_trades(
        self, db_session: AsyncSession
    ) -> None:
        await _seed(
            db_session,
            "AGREES",
            market_cap=Decimal("60000000"),
            reference_mcap=Decimal("50000000"),
        )
        assert await _candidates(db_session) == {"AGREES"}

    async def test_a_token_the_provider_has_no_figure_for_is_judged_by_the_rest(
        self, db_session: AsyncSession
    ) -> None:
        """Absent evidence is not evidence of a bad price."""
        await _seed(db_session, "NOREF", market_cap=Decimal("60000000"))
        assert await _candidates(db_session) == {"NOREF"}
