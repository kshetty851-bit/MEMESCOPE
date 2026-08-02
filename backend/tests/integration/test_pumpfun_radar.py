"""Pump.fun Radar discovery admission and HTTP contract."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.market import TokenMarketSnapshot
from app.models.token import DiscoveredToken
from app.services.pumpfun_radar import PumpfunRadarPolicy, PumpfunRadarScanner

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
PUMP = settings.PUMPFUN_PROGRAM_ID


async def _seed(
    session: AsyncSession,
    *,
    mint: str,
    age_days: int,
    market_cap: Decimal = Decimal("100000"),
    liquidity: Decimal = Decimal("10000"),
    source_program: str = PUMP,
) -> None:
    token = DiscoveredToken(
        mint_address=mint,
        name=f"Token {mint[-1]}",
        symbol=f"T{mint[-1]}",
        signature=f"signature-{mint}",
        slot=1,
        source_program=source_program,
        block_time=NOW - timedelta(days=age_days),
    )
    session.add(token)
    await session.flush()
    session.add(
        TokenMarketSnapshot(
            token_id=token.id,
            mint_address=mint,
            captured_at=NOW,
            market_cap=market_cap,
            liquidity_usd=liquidity,
            volume_24h=Decimal("25000"),
            provider="test",
        )
    )
    await session.flush()


def _policy() -> PumpfunRadarPolicy:
    return PumpfunRadarPolicy(
        program_id=PUMP,
        min_age_days=6,
        max_age_days=8,
        min_market_cap=Decimal("50000"),
        min_liquidity=Decimal("5000"),
        batch_limit=100,
    )


async def test_age_and_market_filters_apply_to_latest_pumpfun_snapshot(
    db_session: AsyncSession,
) -> None:
    await _seed(db_session, mint="PumpRadarAgeSix111111111111111111111111111", age_days=6)
    await _seed(db_session, mint="PumpRadarAgeEight11111111111111111111111111", age_days=8)
    await _seed(db_session, mint="PumpRadarTooYoung11111111111111111111111111", age_days=5)
    await _seed(db_session, mint="PumpRadarTooOld1111111111111111111111111111", age_days=9)
    await _seed(
        db_session,
        mint="PumpRadarThin111111111111111111111111111111",
        age_days=7,
        liquidity=Decimal("4999"),
    )
    await _seed(
        db_session,
        mint="OtherProgram11111111111111111111111111111111",
        age_days=7,
        source_program="other-program",
    )

    candidates = await PumpfunRadarScanner(db_session, policy=_policy()).candidates(now=NOW)

    assert {candidate.token_address for candidate in candidates} == {
        "PumpRadarAgeSix111111111111111111111111111",
        "PumpRadarAgeEight11111111111111111111111111",
    }
    assert {candidate.age_days for candidate in candidates} == {Decimal(6), Decimal(8)}
    assert all(candidate.holder_count is None for candidate in candidates)


async def test_discovered_api_returns_admission_candidates(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    now = datetime.now(UTC)
    token = DiscoveredToken(
        mint_address="PumpRadarApi11111111111111111111111111111111",
        name="Radar API",
        symbol="RAPI",
        signature="signature-api",
        slot=2,
        source_program=PUMP,
        block_time=now - timedelta(days=7),
    )
    db_session.add(token)
    await db_session.flush()
    db_session.add(
        TokenMarketSnapshot(
            token_id=token.id,
            mint_address=token.mint_address,
            captured_at=now,
            market_cap=Decimal("100000"),
            liquidity_usd=Decimal("10000"),
            volume_24h=Decimal("25000"),
            provider="test",
        )
    )
    await db_session.flush()
    response = await client.get(f"{settings.API_V1_PREFIX}/radar/discovered")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["token"] == token.mint_address
    assert item["symbol"] == "RAPI"
    assert Decimal(item["market_cap"]) == Decimal("100000")
    assert Decimal(item["liquidity"]) == Decimal("10000")
    assert Decimal(item["volume"]) == Decimal("25000")
    assert item["last_scan_time"] is not None
