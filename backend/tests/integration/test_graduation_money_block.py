"""The lab refuses what the real wallet's money checks refuse: in the fast
arms' buy, and in a restatement of trades already booked."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core import rug_money
from app.labs.graduation import moneyblock
from app.labs.graduation.models import GradOperator, GradPaperPosition
from app.labs.graduation.tournament import Tournament
from tests.integration.test_graduation_fast_arms import (
    MINT,
    NOW,
    _setup,
    history,
    readers,
)

pytestmark = pytest.mark.integration

BLOCKED = "DyaESzDfBLtbvKz7iM5Th6nsbsGSpjt5NLXuieigRcZX"


def trade(mint: str, *, book: str, opened, net: str) -> GradPaperPosition:
    return GradPaperPosition(
        id=uuid.uuid4(), book=book, mint=mint, symbol=mint[:4], opened_at=opened,
        closed_at=opened + timedelta(minutes=4), open_quote=Decimal("0.0005"),
        open_fill=Decimal("0.0005"), close_quote=Decimal("0.0005"),
        close_fill=Decimal("0.0005"),
        notional_usd=Decimal(100), notional_quote=Decimal(1), sol_usd_at_open=Decimal(100),
        tokens=Decimal(2000), peak_quote=Decimal("0.0005"), last_quote=Decimal("0.0005"),
        net_return=Decimal(net), pnl_usd=Decimal(net) * 100, close_reason="max_hold")


async def test_a_fast_arm_will_not_buy_a_coin_behind_a_rug_an_hour_ago(db_session) -> None:
    await _setup(db_session)
    # WalletA's last coin rugged and closed 30 minutes ago.
    db_session.add_all([history("RUG1", {"WalletA"}, True, NOW - timedelta(minutes=30)),
                        trade("RUG1", book="BASE_75k_5m", opened=NOW - timedelta(minutes=34),
                              net="-0.9")])
    await db_session.flush()
    pool_reader, operator_reader, _ = readers()
    await Tournament(db_session, now=NOW, pool_reader=pool_reader,
                     operator_reader=operator_reader, money_checks=True)._fill_fast()
    await db_session.flush()
    bought = set((await db_session.scalars(
        select(GradPaperPosition.mint).where(GradPaperPosition.opened_at == NOW))).all())
    assert MINT["A"] not in bought                     # refused by every arm
    assert {MINT["B"], MINT["C"], MINT["U"]} <= bought  # the rest trade as before
    # ... and its operator is still recorded, as every graduation is.
    assert (await db_session.get(GradOperator, MINT["A"])).ids == ["FunderT", "WalletA"]


async def test_the_regular_books_see_the_same_refusals(db_session) -> None:
    db_session.add_all([
        history("RUG2", {"Op"}, True, NOW - timedelta(hours=1)),
        trade("RUG2", book="B3_198k_4m", opened=NOW - timedelta(hours=1, minutes=4),
              net="-0.95"),
        history("LINKED", {"Op", "W1"}, False, NOW),
        history("OLDRUG", {"Late"}, True, NOW - timedelta(hours=4)),
        trade("OLDRUG", book="B3_198k_4m", opened=NOW - timedelta(hours=4, minutes=4),
              net="-0.9"),
        history("STALE", {"Late"}, False, NOW),         # its rug is outside the 3 hours
        history("KNOWN", {BLOCKED}, False, NOW),
    ])
    await db_session.flush()
    got = await moneyblock.refusals(db_session, ["LINKED", "STALE", "KNOWN", "NONE"], NOW)
    assert got == {"LINKED": moneyblock.LINKED, "KNOWN": moneyblock.KNOWN}


async def test_booked_trades_are_restated_as_the_checks_stood_when_opened(db_session) -> None:
    since = NOW - timedelta(hours=6)
    before_live = rug_money.BLOCKED_SINCE[BLOCKED] - timedelta(minutes=1)
    db_session.add_all([
        history("RUG3", {"Op3"}, True, NOW - timedelta(hours=2)),
        trade("RUG3", book="BASE_75k_5m", opened=NOW - timedelta(hours=2, minutes=5),
              net="-0.9"),
        history("NEXT", {"Op3"}, False, NOW),
        trade("NEXT", book="BASE_75k_5m", opened=NOW - timedelta(hours=1), net="0.2"),
        trade("NEXT", book="B3_198k_4m", opened=NOW - timedelta(hours=1), net="0.1"),
        history("CLEAN", {"Nobody"}, False, NOW),
        trade("CLEAN", book="BASE_75k_5m", opened=NOW - timedelta(hours=1), net="0.05"),
        history("EARLY", {BLOCKED}, False, before_live),
        trade("EARLY", book="BASE_75k_5m", opened=before_live, net="0.03"),
    ])
    await db_session.flush()
    dry = await moneyblock.restate(db_session, since=min(since, before_live), apply=False)
    assert dry["marked"] == {"BASE_75k_5m": 1, "B3_198k_4m": 1}   # NEXT, in both books
    assert dry["pnl_usd_left_out"] == {"BASE_75k_5m": 20.0, "B3_198k_4m": 10.0}
    await moneyblock.restate(db_session, since=min(since, before_live), apply=True)
    await db_session.flush()
    marked = (await db_session.scalars(select(GradPaperPosition.mint).where(
        GradPaperPosition.excluded == moneyblock.EXCLUDED))).all()
    assert sorted(marked) == ["NEXT", "NEXT"]    # EARLY: the block was not live yet
    again = await moneyblock.restate(db_session, since=min(since, before_live), apply=True)
    assert again["marked"] == {}
