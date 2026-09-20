"""The lab refuses what the real wallet's money checks refuse: in the fast
arms' buy, in a restatement of trades already booked, and - from 2026-09-20 -
on an operator's own record of earlier rugs."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core import rug_money
from app.labs.graduation import config, moneyblock
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


def operator(mint: str, ids: set[str], rugged: bool | None, at) -> GradOperator:
    return GradOperator(mint=mint, pool="p", entry_at=at, price_native=Decimal("0.0001"),
                        ids=sorted(ids), label_due_at=at + timedelta(minutes=5),
                        rugged=rugged, labelled_at=None if rugged is None else at,
                        source="tape")


async def test_an_address_with_a_record_of_rugs_is_refused(db_session) -> None:
    """Three of the four rugs that cost the fresh $75k book came from wallets
    nobody had seen. This refuses the ones with a record, on the record."""
    moneyblock._REPEAT = None
    old = NOW - timedelta(days=1)
    rows = []
    for i in range(config.REPEAT_MIN_COINS):
        share = i * 100 < config.REPEAT_MIN_COINS * config.REPEAT_MIN_RUG_PCT
        rows.append(operator(f"dirty{i}", {"Dirty"}, share, old))
        rows.append(operator(f"clean{i}", {"Clean"}, False, old))
    # A rug nobody has labelled yet is not evidence.
    rows.append(operator("late", {"Slow"}, None, old))
    rows += [operator(f"slow{i}", {"Slow"}, None, old) for i in range(config.REPEAT_MIN_COINS)]
    rows += [operator("coinD", {"Dirty", "Friend"}, None, NOW),
             operator("coinC", {"Clean"}, None, NOW),
             operator("coinS", {"Slow"}, None, NOW)]
    db_session.add_all(rows)
    await db_session.flush()

    dirty = await moneyblock.repeat_rug_ids(db_session, NOW)
    assert "Dirty" in dirty and "Clean" not in dirty and "Slow" not in dirty
    moneyblock._REPEAT = None
    got = await moneyblock.refusals(db_session, ["coinD", "coinC", "coinS"], NOW)
    assert got == {"coinD": moneyblock.REPEAT}
    # ... and not with hindsight: before those rugs existed, nothing is refused.
    moneyblock._REPEAT = None
    assert await moneyblock.repeat_rug_ids(db_session, old - timedelta(days=1)) == frozenset()
    moneyblock._REPEAT = None


async def test_a_deep_coin_the_fast_path_missed_is_read_at_the_buy(db_session) -> None:
    """EVO (20 Sep) was bought by three books with no record at all, so no
    check ran on it. One deep coin in five was in that state."""
    from types import SimpleNamespace

    from app.labs.graduation.tournament import Tournament, graduation_pool

    deep = SimpleNamespace(mint=MINT["A"], liquidity_usd=Decimal(120_000),
                           graduated_at=NOW - timedelta(seconds=40),
                           price_native=Decimal("0.0001"))
    shallow = SimpleNamespace(mint=MINT["B"], liquidity_usd=Decimal(20_000),
                              graduated_at=NOW, price_native=Decimal("0.0001"))

    async def operator_reader(mint: str, pool: str) -> frozenset[str]:
        return frozenset({BLOCKED, "Someone"})

    t = Tournament(db_session, now=NOW, operator_reader=operator_reader, money_checks=True)
    assert await t._record_late([deep, shallow]) == 1
    await db_session.flush()
    row = await db_session.get(GradOperator, MINT["A"])
    assert row is not None and row.source == "entry" and BLOCKED in row.ids
    assert row.pool == graduation_pool(MINT["A"]) and row.depth_usd == Decimal(120_000)
    assert await db_session.get(GradOperator, MINT["B"]) is None   # too shallow to record
    # The point of recording it: the checks can now refuse it.
    moneyblock._REPEAT = None
    got = await moneyblock.refusals(db_session, [MINT["A"]], NOW)
    assert got == {MINT["A"]: moneyblock.KNOWN}
    moneyblock._REPEAT = None
    # Read once: a second tick finds it recorded and reads nothing.
    assert await t._record_late([deep]) == 0
