"""The driver's job is mostly to decline. These test the declining.

It stands between a paper strategy's opinion and real money, so every guard it
carries is tested from the side that wants through.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.lab.service import LabService
from app.models.lab import LabDecision
from app.models.real_wallet_execution import RealWalletLiveIntent
from app.real_wallet.autotrade import AutotradeSwitchService
from app.real_wallet.driver import MAX_DECISION_AGE, RealWalletDriver

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
WALLET = "7WctMGpqz1tGkYStBBjJRMnmuh9uwJubYV2tL4pLwRr9"
MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    # The driver reads the chain balance because the canary ceiling refuses an
    # unmeasured wallet. These tests are about the driver's own guards, so the
    # read is stubbed to a funded-but-tiny wallet.
    async def _lamports(self, wallet):  # noqa: ARG001
        return 50_000_000

    monkeypatch.setattr(RealWalletDriver, "_wallet_lamports", _lamports)
    monkeypatch.setattr(settings, "REAL_WALLET_PUBLIC_KEY", WALLET)
    monkeypatch.setattr(settings, "REAL_WALLET_ENTRY_SIZE_USD", Decimal("5"))
    monkeypatch.setattr(settings, "REAL_WALLET_MAX_TRADE_USD", Decimal("5"))
    monkeypatch.setattr(settings, "REAL_WALLET_MAX_OPEN_POSITIONS", 1)


async def _decision(session, *, strategy="V6-06", mint=MINT, at=None, eligible=True):
    strat = await LabService(session).activate(valid_from=NOW - timedelta(days=1))
    row = (await session.execute(
        select(LabDecision).limit(1)
    )).scalars().first()
    from app.models.lab import LabStrategy

    s = (await session.execute(
        select(LabStrategy).where(LabStrategy.strategy_id == strategy)
    )).scalars().first()
    session.add(LabDecision(
        strategy_row_id=s.id, strategy_id=strategy, mint_address=mint,
        checkpoint_at=(at or NOW), checkpoint_minutes=30, decided_at=(at or NOW),
        eligible=eligible, features={}, requested_size_usd=Decimal("10"),
    ))
    await session.flush()


async def _switch_on(session, strategy="V6-06"):
    await AutotradeSwitchService(session).start(
        actor="op@x.com", reason="testing the driver", strategy_id=strategy, at=NOW
    )


async def test_it_does_nothing_while_the_switch_is_off(db_session):
    await _decision(db_session)
    out = await RealWalletDriver(db_session).tick(now=NOW)
    assert out.created == 0
    assert out.skipped == "autotrade_switch_off"


async def test_it_creates_one_intent_when_everything_allows_it(db_session):
    await _decision(db_session)
    await _switch_on(db_session)
    out = await RealWalletDriver(db_session).tick(now=NOW)
    assert out.created == 1
    assert out.mint == MINT
    intent = (await db_session.execute(select(RealWalletLiveIntent))).scalars().one()
    assert intent.side == "BUY"
    assert intent.requested_usd == Decimal("5")
    assert intent.wallet_public_key == WALLET
    assert intent.strategy_id == "V6-06"


async def test_it_creates_at_most_one_intent_per_tick(db_session):
    for i in range(4):
        await _decision(db_session, mint=f"MINT{i}" + "x" * 20)
    await _switch_on(db_session)
    out = await RealWalletDriver(db_session).tick(now=NOW)
    assert out.created == 1
    rows = (await db_session.execute(select(RealWalletLiveIntent))).scalars().all()
    assert len(rows) == 1


async def test_it_never_trades_the_same_mint_twice(db_session):
    await _decision(db_session)
    await _switch_on(db_session)
    assert (await RealWalletDriver(db_session).tick(now=NOW)).created == 1
    second = await RealWalletDriver(db_session).tick(now=NOW)
    assert second.created == 0
    assert second.skipped == "no_fresh_candidate"


async def test_it_only_trades_the_nominated_strategy(db_session):
    await _decision(db_session, strategy="V6-05")
    await _switch_on(db_session, strategy="V6-06")
    out = await RealWalletDriver(db_session).tick(now=NOW)
    assert out.created == 0
    assert out.skipped == "no_fresh_candidate"


async def test_it_ignores_a_decision_the_strategy_refused(db_session):
    await _decision(db_session, eligible=False)
    await _switch_on(db_session)
    assert (await RealWalletDriver(db_session).tick(now=NOW)).created == 0


async def test_it_ignores_a_stale_decision(db_session):
    """A decision from an hour ago describes a market that no longer exists."""
    await _decision(db_session, at=NOW - MAX_DECISION_AGE - timedelta(minutes=1))
    await _switch_on(db_session)
    out = await RealWalletDriver(db_session).tick(now=NOW)
    assert out.created == 0
    assert out.skipped == "no_fresh_candidate"


async def test_an_unconfigured_entry_size_refuses(db_session, monkeypatch):
    monkeypatch.setattr(settings, "REAL_WALLET_ENTRY_SIZE_USD", Decimal("0"))
    await _decision(db_session)
    await _switch_on(db_session)
    out = await RealWalletDriver(db_session).tick(now=NOW)
    assert out.skipped == "entry_size_not_configured"


async def test_an_unconfigured_wallet_refuses(db_session, monkeypatch):
    monkeypatch.setattr(settings, "REAL_WALLET_PUBLIC_KEY", "")
    await _decision(db_session)
    await _switch_on(db_session)
    assert (await RealWalletDriver(db_session).tick(now=NOW)).skipped == \
        "wallet_not_configured"


async def test_an_armed_kill_switch_refuses(db_session):
    from app.real_wallet.live_repository import LiveIntentRepository

    await _decision(db_session)
    await _switch_on(db_session)
    await LiveIntentRepository(db_session).activate_kill_switch(
        kind="manual", reason="testing", actor="op@x.com", at=NOW
    )
    out = await RealWalletDriver(db_session).tick(now=NOW)
    assert out.created == 0
    assert out.skipped == "kill_switch_active"


async def test_stopping_the_switch_stops_new_intents_immediately(db_session):
    await _decision(db_session)
    await _switch_on(db_session)
    assert (await RealWalletDriver(db_session).tick(now=NOW)).created == 1
    await AutotradeSwitchService(db_session).stop(
        actor="op@x.com", reason="enough", at=NOW
    )
    await _decision(db_session, mint="ANOTHER" + "x" * 20)
    out = await RealWalletDriver(db_session).tick(now=NOW)
    assert out.created == 0
    assert out.skipped == "autotrade_switch_off"


async def test_an_unreadable_balance_is_a_skip_never_a_trade(db_session, monkeypatch):
    """The canary ceiling only means something if it was measured. An RPC that
    cannot answer must stop the trade, not be assumed away."""
    async def _none(self, wallet):  # noqa: ARG001
        return None

    monkeypatch.setattr(RealWalletDriver, "_wallet_lamports", _none)
    await _decision(db_session)
    await _switch_on(db_session)
    out = await RealWalletDriver(db_session).tick(now=NOW)
    assert out.created == 0
    assert out.skipped == "wallet_balance_unreadable"


async def test_a_wallet_over_the_canary_ceiling_is_refused(db_session, monkeypatch):
    """Overfunding blocks trading rather than enabling it — the ceiling keeps
    the canary small, so a large balance is a refusal."""
    async def _huge(self, wallet):  # noqa: ARG001
        return 5_000_000_000  # 5 SOL, far above REAL_WALLET_MAX_BALANCE_SOL

    monkeypatch.setattr(RealWalletDriver, "_wallet_lamports", _huge)
    await _decision(db_session)
    await _switch_on(db_session)
    out = await RealWalletDriver(db_session).tick(now=NOW)
    assert out.created == 0
    assert "MAX_WALLET_BALANCE" in (out.skipped or "")
