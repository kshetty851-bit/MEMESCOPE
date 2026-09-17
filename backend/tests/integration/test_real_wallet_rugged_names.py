"""Karthik's rule, 2026-09-17: never buy a token whose NAME has already rugged.

Made against the measurement, not because of it — over 2,830 graduations in the
week to 2026-09-17 a name that had rugged before rugged LESS often than the rest
(4.41% against 8.23%), and the rule would not have stopped ZBCN, whose name had
not rugged in our records. It is his wallet and his call; these tests pin what
the switch does, not whether it is wise.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.labs.graduation.models import GradPaperPosition, GradToken
from app.real_wallet_safety.service import RealWalletSafetyGate

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC) - timedelta(hours=3)
RUGGED_MINT = "RuggedMint1111111111111111111111111111111111"
FRESH_MINT = "FreshMint11111111111111111111111111111111111"
CLEAN_MINT = "CleanMint111111111111111111111111111111111111"


def _gate(session: AsyncSession) -> RealWalletSafetyGate:
    # No network from this path: the name check is one query and nothing else.
    return RealWalletSafetyGate(session, rpc=object(), jupiter=object())


async def _seed(session: AsyncSession) -> None:
    session.add_all([
        GradToken(mint=RUGGED_MINT, symbol=" ZBCN ", first_seen_at=NOW),
        GradToken(mint=FRESH_MINT, symbol="zbcn", first_seen_at=NOW + timedelta(hours=1)),
        GradToken(mint=CLEAN_MINT, symbol="NEWNAME", first_seen_at=NOW + timedelta(hours=1)),
        GradPaperPosition(
            id=uuid.uuid4(), book="B3_198k_4m", mint=RUGGED_MINT, symbol="ZBCN",
            opened_at=NOW, closed_at=NOW + timedelta(minutes=4),
            open_quote=Decimal("0.0005"), open_fill=Decimal("0.0005"),
            close_quote=Decimal("0.00003"), close_fill=Decimal("0.00003"),
            notional_usd=Decimal(100), notional_quote=Decimal(1), sol_usd_at_open=Decimal(100),
            tokens=Decimal(2000), peak_quote=Decimal("0.0005"), last_quote=Decimal("0.00003"),
            net_return=Decimal("-0.93"), pnl_usd=Decimal("-93"), close_reason="max_hold"),
    ])
    await session.flush()


async def test_a_name_that_rugged_before_is_refused(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed(db_session)
    monkeypatch.setattr(settings, "REAL_WALLET_BLOCK_RUGGED_SYMBOLS", True)
    gate = _gate(db_session)

    # Same name, different token, whitespace and case ignored.
    assert await gate._symbol_has_rugged(FRESH_MINT, None) is True
    # A name nothing has rugged under is fine.
    assert await gate._symbol_has_rugged(CLEAN_MINT, None) is False
    # The rugged token's own row never blocks itself: the wallet already
    # refuses a mint it has traded, and this rule is about the NAME.
    assert await gate._symbol_has_rugged(RUGGED_MINT, None) is False
    # A token nobody has named cannot be matched, so it is allowed through.
    unknown = "UnknownMint1111111111111111111111111111111"
    assert await gate._symbol_has_rugged(unknown, None) is False


async def test_the_switch_governs_it(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed(db_session)
    monkeypatch.setattr(settings, "REAL_WALLET_BLOCK_RUGGED_SYMBOLS", False)
    assert await _gate(db_session)._symbol_has_rugged(FRESH_MINT, None) is False


async def test_a_smaller_loss_than_the_rug_line_does_not_block(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """-50% is the line the lab counts rugs at. A bad trade is not a rug."""
    await _seed(db_session)
    monkeypatch.setattr(settings, "REAL_WALLET_BLOCK_RUGGED_SYMBOLS", True)
    monkeypatch.setattr(settings, "REAL_WALLET_RUG_RETURN", Decimal("-0.95"))
    assert await _gate(db_session)._symbol_has_rugged(FRESH_MINT, None) is False
