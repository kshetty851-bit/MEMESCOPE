"""The rug brake (Karthik, 2026-10-03): one more rug while the main wallet is
under $150 stops the trading for every wallet; nothing else stops it.
Lowered to $50 on 2026-10-04 at his request."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from app.models.real_wallet_execution import RealWalletPosition
from app.real_wallet import rug_brake
from app.real_wallet.autotrade import AutotradeSwitchService

pytestmark = pytest.mark.integration

START = rug_brake.ARMED_AT + timedelta(minutes=10)


def closed(mint: str, *, at, got_back: str, wallet: str = "OwnerWallet") -> RealWalletPosition:
    """0.4 SOL in, `got_back` SOL out, closed at `at`."""
    return RealWalletPosition(
        mint_address=mint, status="CLOSED", quantity=Decimal(100),
        entry_price_usd=Decimal("0.5"),
        opened_at=at - timedelta(minutes=5), closed_at=at, wallet_public_key=wallet,
        entry_actual_input_amount=Decimal("0.4"), exit_actual_output_amount=Decimal(got_back))


async def _on(session):
    await AutotradeSwitchService(session).start(
        actor="op@x.com", reason="testing the brake", strategy_id="V7-06", at=START)


def worth(value):
    async def read():
        return None if value is None else Decimal(value)
    return read


@pytest.fixture(autouse=True)
def _fresh():
    rug_brake._weighed.clear()


async def test_a_rug_under_50_stops_everything(db_session):
    await _on(db_session)
    db_session.add(closed("RUG", at=START + timedelta(minutes=30), got_back="0.01",
                          wallet="UserOne"))
    await db_session.flush()
    now = START + timedelta(minutes=31)
    assert await rug_brake.pull_if_due(db_session, now, worth("45.23")) is True
    state = await AutotradeSwitchService(db_session).state()
    assert (state.enabled, state.stopped_by) == (False, "rug_brake")
    assert "$45.23" in state.stop_reason


async def test_a_rug_at_50_or_more_does_not_stop_it_and_is_not_weighed_again(db_session):
    await _on(db_session)
    db_session.add(closed("RUG", at=START + timedelta(minutes=30), got_back="0.01"))
    await db_session.flush()
    now = START + timedelta(minutes=31)
    assert await rug_brake.pull_if_due(db_session, now, worth("50.00")) is False
    # The same rug, the wallet since fallen: not this rug's to stop.
    assert await rug_brake.pull_if_due(db_session, now, worth("30.00")) is False
    assert (await AutotradeSwitchService(db_session).state()).enabled is True


async def test_winners_old_rugs_and_rugs_before_the_last_start_do_not_count(db_session):
    db_session.add_all([
        closed("BEFORE_ARMED", at=rug_brake.ARMED_AT - timedelta(hours=3), got_back="0.01"),
        closed("BEFORE_START", at=START - timedelta(minutes=1), got_back="0.01"),
        closed("WIN", at=START + timedelta(minutes=30), got_back="0.41"),
        # Exactly half back is not a rug.
        closed("HALF", at=START + timedelta(minutes=40), got_back="0.2"),
    ])
    await _on(db_session)
    await db_session.flush()
    later = START + timedelta(hours=1)
    assert await rug_brake.pull_if_due(db_session, later, worth("20")) is False
    assert (await AutotradeSwitchService(db_session).state()).enabled is True


async def test_an_unreadable_worth_waits_for_the_next_pass(db_session):
    await _on(db_session)
    db_session.add(closed("RUG", at=START + timedelta(minutes=30), got_back="0.01"))
    await db_session.flush()
    now = START + timedelta(minutes=31)
    assert await rug_brake.pull_if_due(db_session, now, worth(None)) is False
    assert await rug_brake.pull_if_due(db_session, now, worth("40")) is True


async def test_nothing_happens_while_already_stopped(db_session):
    db_session.add(closed("RUG", at=START + timedelta(minutes=30), got_back="0.01"))
    await db_session.flush()
    asked = []

    async def read():
        asked.append(1)
        return Decimal(1)
    assert await rug_brake.pull_if_due(db_session, START + timedelta(hours=1), read) is False
    assert asked == [], "a stopped switch needs no balance read"
