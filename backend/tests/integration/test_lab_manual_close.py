"""Closing a Lab position by hand — the only exit no frozen rule caused.

The button exists because the owner asked for it. These tests are about the
two things that must remain true once it does.

**It must be visible in the record.** The tournament's entire claim is that
every result followed the frozen registry. A hand-closed position did not, so
it carries `manual_close` and can be counted apart from the rest. Blending it
in as an ordinary exit would turn the leaderboard into a number nobody can
cite — which is worse than not having the button.

**It must not pay a price the strategies could never have got.** The fill runs
through the same `_mark` and the same execution model as `settle`: the stale
guard, the glitch band, and impact against real depth. Selling by hand at a
last healthy print would book a profit the market would not have paid, and a
tournament that can be rescued by clicking is measuring the clicking.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from app.lab import spec
from app.lab.service import LabService
from app.models.lab import LabPosition, LabStrategy
from app.models.market import TokenMarketSnapshot, TradingStatus

from tests.integration.test_lab_accounting import (
    NOW, VALID_FROM, _TRADER_A, _open_one,
)

pytestmark = pytest.mark.integration

ACTOR = "owner@example.com"


async def _one_open(db_session, svc, mint: str, liq: D = D("600000")):
    await _open_one(db_session, svc, mint=mint, liq=liq)
    return (await db_session.execute(
        select(LabPosition).where(LabPosition.strategy_id == _TRADER_A)
    )).scalars().first()


async def _price(db_session, pos, *, at, price: D, liq: D = D("600000"),
                 status=TradingStatus.TRADING):
    db_session.add(TokenMarketSnapshot(
        token_id=pos.token_id, mint_address=pos.mint_address, captured_at=at,
        price_usd=price, liquidity_usd=liq, market_cap=D("6000000"),
        trading_status=status, provider="test", suspect=False,
    ))
    await db_session.flush()


# --------------------------------------------------------------------------
# it closes, and it says so
# --------------------------------------------------------------------------


async def test_it_closes_the_position_and_labels_the_exit_as_manual(db_session):
    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    pos = await _one_open(db_session, svc, "M" + "1" * 20)
    await _price(db_session, pos, at=NOW + timedelta(minutes=1), price=D("0.0011"))

    out = await svc.close_manually(position_id=pos.id,
                                   now=NOW + timedelta(minutes=2), actor=ACTOR)
    await db_session.refresh(pos)

    assert out["closed"] is True
    assert pos.status == "closed"
    assert pos.exit_reason == "manual_close"
    # Distinguishable from every rule-driven exit, which is the whole point.
    assert not pos.exit_reason.startswith("target")
    assert pos.exit_reason not in {"dead_zero", "time_6h", "trailing_stop"}


async def test_the_cash_comes_back_to_the_strategy(db_session):
    """A closed position that did not return its stake would quietly delete
    capital from the wallet, and the equity curve would never recover."""
    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    pos = await _one_open(db_session, svc, "M" + "2" * 20)
    row = (await db_session.execute(
        select(LabStrategy).where(LabStrategy.id == pos.strategy_row_id)
    )).scalars().first()
    before = row.cash
    await _price(db_session, pos, at=NOW + timedelta(minutes=1), price=D("0.0011"))

    out = await svc.close_manually(position_id=pos.id,
                                   now=NOW + timedelta(minutes=2), actor=ACTOR)
    await db_session.refresh(row)

    # `cash` is persisted at the column's scale, so compare at that scale
    # rather than against the full-precision Decimal the service returned.
    assert abs(row.cash - (before + out["proceeds_usd"])) < D("0.001")
    assert out["pnl_usd"] == out["proceeds_usd"] - pos.size_usd


# --------------------------------------------------------------------------
# the fill is not a favour
# --------------------------------------------------------------------------


async def test_the_fill_pays_impact_rather_than_the_chart_price(db_session):
    """Sold into shallow depth, a hand exit must lose to the quoted price the
    same way every other exit does."""
    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    # Entered at the depth the rule demands (V7-04 wants >= $300k), then the
    # pool thins out — which is the case that actually costs a seller.
    pos = await _one_open(db_session, svc, "M" + "3" * 20, liq=D("600000"))
    await _price(db_session, pos, at=NOW + timedelta(minutes=1),
                 price=D("0.002"), liq=D("30000"))

    out = await svc.close_manually(position_id=pos.id,
                                   now=NOW + timedelta(minutes=2), actor=ACTOR)
    naive = pos.quantity_remaining * D("0.002")
    assert out["proceeds_usd"] < naive, "a manual sell must not fill at mid"


async def test_a_dead_pool_pays_zero_by_hand_too(db_session):
    """The rescue everyone reaches for. Clicking sell on a rug must not book
    its last healthy print — that is the fiction the execution model exists to
    refuse, and it does not care who asked."""
    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    pos = await _one_open(db_session, svc, "M" + "4" * 20)
    await _price(db_session, pos, at=NOW + timedelta(minutes=1), price=D("0.005"),
                 status=TradingStatus.INACTIVE)

    out = await svc.close_manually(position_id=pos.id,
                                   now=NOW + timedelta(minutes=2), actor=ACTOR)
    await db_session.refresh(pos)
    assert out["closed"] is True
    assert pos.exit_price == 0
    assert out["proceeds_usd"] == 0


async def test_an_unmarkable_position_is_refused_not_closed(db_session):
    """No fresh print means no price anyone can trade against. Refusing leaves
    the position open for the next tick; closing would invent the number."""
    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    pos = await _one_open(db_session, svc, "M" + "5" * 20)
    # No snapshot after entry at all — nothing to mark against.
    out = await svc.close_manually(position_id=pos.id,
                                   now=NOW + timedelta(hours=3), actor=ACTOR)
    await db_session.refresh(pos)

    assert out["closed"] is False
    assert out["reason"] == "unmarkable"
    assert pos.status == "open"


# --------------------------------------------------------------------------
# the ordinary races
# --------------------------------------------------------------------------


async def test_closing_twice_is_not_an_error(db_session):
    """Two clicks, or a settle that won the race. Both are ordinary and must
    not raise — and the second must not pay out again."""
    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    pos = await _one_open(db_session, svc, "M" + "6" * 20)
    await _price(db_session, pos, at=NOW + timedelta(minutes=1), price=D("0.0011"))
    at = NOW + timedelta(minutes=2)

    first = await svc.close_manually(position_id=pos.id, now=at, actor=ACTOR)
    row = (await db_session.execute(
        select(LabStrategy).where(LabStrategy.id == pos.strategy_row_id)
    )).scalars().first()
    await db_session.refresh(row)
    cash_after_first = row.cash

    second = await svc.close_manually(position_id=pos.id, now=at, actor=ACTOR)
    await db_session.refresh(row)

    assert first["closed"] is True
    assert second["closed"] is False
    assert second["reason"] == "already_closed"
    assert row.cash == cash_after_first, "a second click must not pay twice"


async def test_an_unknown_position_is_reported_not_raised(db_session):
    svc = LabService(db_session)
    await svc.activate(valid_from=VALID_FROM)
    out = await svc.close_manually(position_id=uuid.uuid4(), now=NOW, actor=ACTOR)
    assert out == {"closed": False, "reason": "not_found"}
