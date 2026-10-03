"""Karthik's rule, 2026-10-03: never buy a coin whose creator launched another
coin before it. Since the partners timer the 16 repeat-creator trades made
-$50.19 (one rug); these tests pin what the switch does, not whether it is wise.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.token import DiscoveredToken
from app.real_wallet_safety.service import RealWalletSafetyGate

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC) - timedelta(hours=3)


def _gate(session: AsyncSession) -> RealWalletSafetyGate:
    # No network from this path: the creator check is one query.
    return RealWalletSafetyGate(session, rpc=object(), jupiter=object())


async def _token(session: AsyncSession, creator: str | None, at: datetime) -> DiscoveredToken:
    token = DiscoveredToken(mint_address=f"Mint{uuid.uuid4().hex}",
                            signature=f"sig-{uuid.uuid4()}", slot=1,
                            creator_address=creator, block_time=at)
    session.add(token)
    await session.flush()
    return token


async def test_a_creator_who_launched_before_is_refused_and_a_first_launch_is_not(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "REAL_WALLET_BLOCK_REPEAT_CREATORS", True)
    gate = _gate(db_session)
    first = await _token(db_session, "RepeatCreator", NOW)
    second = await _token(db_session, "RepeatCreator", NOW + timedelta(hours=1))
    other = await _token(db_session, "NewCreator", NOW + timedelta(hours=1))

    assert await gate._creator_launched_before(second) is True
    # The first launch is not blocked by the creator's LATER coin.
    assert await gate._creator_launched_before(first) is False
    assert await gate._creator_launched_before(other) is False


async def test_missing_data_lets_it_through_and_the_switch_governs_it(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "REAL_WALLET_BLOCK_REPEAT_CREATORS", True)
    gate = _gate(db_session)
    await _token(db_session, "RepeatCreator", NOW)
    second = await _token(db_session, "RepeatCreator", NOW + timedelta(hours=1))
    nameless = await _token(db_session, None, NOW + timedelta(hours=1))

    assert await gate._creator_launched_before(None) is False
    assert await gate._creator_launched_before(nameless) is False

    monkeypatch.setattr(settings, "REAL_WALLET_BLOCK_REPEAT_CREATORS", False)
    assert await gate._creator_launched_before(second) is False
