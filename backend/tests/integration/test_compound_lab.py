"""The Compound Lab's ratchet: bank at +10%, compound from what was REALISED.

The arithmetic here is the whole feature, and one number decides whether it is
honest. A cycle trips on MARKS — cash plus what the book could be sold for —
and then the book is actually sold, which pays impact. Those two figures are
not the same, and compounding from the target instead of from the proceeds
would invent the difference on every cycle, with the error growing as the
wallet grew.

The other thing these hold is isolation. Two tournaments now share the Lab's
tables, and `settle` looks its strategy up by id — so a Compound position
reachable from V7's tick would raise KeyError inside the running tournament
and stop it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from app.compound import spec as cspec
from app.compound.service import CYCLE_EXIT_REASON, CompoundService
from app.lab import spec as v7spec
from app.lab.service import LabService
from app.models.compound import CompoundCycle
from app.models.lab import LabPosition, LabStrategy
from app.models.market import TokenMarketSnapshot, TradingStatus

from tests.integration.test_lab_accounting import NOW, VALID_FROM, _radar_token

pytestmark = pytest.mark.integration


async def _row(db_session):
    return (await db_session.execute(
        select(LabStrategy).where(LabStrategy.spec_hash == cspec.SPEC_HASH)
    )).scalars().first()


# --------------------------------------------------------------------------
# the registry
# --------------------------------------------------------------------------


def test_it_is_a_separate_registry_from_the_running_tournament() -> None:
    """If these hashes ever match, editing one silently rescores the other."""
    assert cspec.SPEC_HASH != v7spec.SPEC_HASH
    assert cspec.SPEC_VERSION != v7spec.SPEC_VERSION


def test_the_wallet_target_is_the_only_target() -> None:
    """A position take-profit would fight the wallet target — the position
    would be cut at 1.25x while the wallet was still short of its 10%, and the
    experiment would measure the position rule instead of the ratchet."""
    s = cspec.STRATEGIES[0]
    assert s.exits.take_profit is None
    assert s.exits.time_exit_hours == 6, "but it must still be bounded by time"


async def test_activation_creates_one_wallet_at_the_book(db_session):
    await CompoundService(db_session).tick(now=NOW)
    row = await _row(db_session)
    assert row is not None
    assert row.strategy_id == "CMP-01"
    assert row.cash == cspec.STARTING_EQUITY


# --------------------------------------------------------------------------
# the cycle
# --------------------------------------------------------------------------


async def test_the_first_cycle_targets_ten_percent_of_the_book(db_session):
    await CompoundService(db_session).tick(now=NOW)
    row = await _row(db_session)
    c = (await db_session.execute(
        select(CompoundCycle).where(CompoundCycle.strategy_row_id == row.id)
    )).scalars().first()
    assert c.cycle_no == 1
    assert c.base_usd == D("100")
    assert c.target_usd == D("110")
    assert c.reached_at is None


async def test_below_target_it_banks_nothing(db_session):
    svc = CompoundService(db_session)
    await svc.tick(now=NOW)
    out = await svc.tick(now=NOW + timedelta(minutes=1))
    # A LIST now, one entry per wallet that banked: the same mechanism drives
    # twenty wallets in Momentum V2, and a bool could not say which.
    assert out["banked"] == []


async def test_reaching_the_target_sells_the_book_and_opens_the_next_cycle(db_session):
    """The ratchet itself."""
    svc = CompoundService(db_session)
    await svc.tick(now=NOW)
    row = await _row(db_session)
    # Put the wallet over its target without touching the market: this test is
    # about the ratchet, and the fill path has its own tests.
    row.cash = D("115")
    await db_session.flush()

    out = await svc.tick(now=NOW + timedelta(minutes=2))
    assert len(out["banked"]) == 1
    banked = out["banked"][0]
    assert banked["strategy_id"] == "CMP-01"
    assert banked["cycle"] == 1
    assert banked["next_cycle"] == 2

    cycles = list((await db_session.execute(
        select(CompoundCycle).where(CompoundCycle.strategy_row_id == row.id)
        .order_by(CompoundCycle.cycle_no)
    )).scalars())
    assert len(cycles) == 2
    first, second = cycles
    assert first.outcome == "target_reached"
    assert first.reached_at is not None
    # The next cycle compounds from what was REALISED, not from the target.
    assert second.base_usd == first.realised_equity
    assert second.target_usd == first.realised_equity * D("1.10")


async def test_it_compounds_from_the_proceeds_not_from_the_target(db_session):
    """The number that decides whether the whole thing is honest.

    A cycle that trips at $115 must carry $115 forward, not the $110 it was
    aiming at — and when selling costs impact, it must carry the lower figure
    the sale actually returned.
    """
    svc = CompoundService(db_session)
    await svc.tick(now=NOW)
    row = await _row(db_session)
    row.cash = D("115")
    await db_session.flush()
    await svc.tick(now=NOW + timedelta(minutes=2))

    second = (await db_session.execute(
        select(CompoundCycle).where(CompoundCycle.strategy_row_id == row.id,
                                    CompoundCycle.cycle_no == 2)
    )).scalars().first()
    assert second.base_usd == D("115"), "carried the realised figure forward"
    assert second.base_usd != D("110"), "not the target it aimed at"
    assert second.target_usd == D("126.5")


async def test_a_cycle_number_is_never_issued_twice(db_session):
    """The guard that makes the tick safe to re-run. Two cycle 2s would give
    the wallet two bases and the later one would win silently."""
    svc = CompoundService(db_session)
    await svc.tick(now=NOW)
    row = await _row(db_session)
    row.cash = D("115")
    await db_session.flush()
    await svc.tick(now=NOW + timedelta(minutes=2))
    await svc.tick(now=NOW + timedelta(minutes=3))
    await svc.tick(now=NOW + timedelta(minutes=4))

    nos = [c.cycle_no for c in (await db_session.execute(
        select(CompoundCycle).where(CompoundCycle.strategy_row_id == row.id)
    )).scalars()]
    assert len(nos) == len(set(nos))


# --------------------------------------------------------------------------
# isolation from the running tournament
# --------------------------------------------------------------------------


async def test_the_compound_tick_never_settles_the_other_tournament(db_session):
    """`settle` used to select EVERY open position. With two registries sharing
    these tables that is someone else's book — and `self._spec.BY_ID[...]`
    would raise KeyError on it, inside whichever tick got there first."""
    lab = LabService(db_session)
    await lab.activate(valid_from=VALID_FROM)
    await _radar_token(db_session, mint="X" + "9" * 20,
                       detected=NOW - timedelta(hours=2), liq=D("600000"),
                       price=D("0.001"), pool="PX99")
    await lab.evaluate_due(now=NOW)
    v7_open = len(list((await db_session.execute(
        select(LabPosition).where(LabPosition.status == "open")
    )).scalars()))
    assert v7_open > 0, "the fixture must leave V7 holding something"

    # The compound tick must run cleanly and leave V7's book untouched.
    await CompoundService(db_session).tick(now=NOW)
    still = len(list((await db_session.execute(
        select(LabPosition).where(LabPosition.status == "open")
    )).scalars()))
    assert still == v7_open


async def test_the_running_tournament_never_settles_compound_positions(db_session):
    """The same guard from the other side, which is the dangerous direction:
    a KeyError here would stop V7."""
    await CompoundService(db_session).tick(now=NOW)
    lab = LabService(db_session)
    await lab.activate(valid_from=VALID_FROM)
    out = await lab.settle(now=NOW + timedelta(minutes=1))
    assert "closed" in out  # it completed rather than raising


def test_a_cycle_close_is_not_recorded_as_a_hand_sell() -> None:
    """Three ways a position can leave the book without its own rule firing —
    a person, a wallet target, a dead pool — and the record must tell them
    apart or none of the exits can be counted."""
    assert CYCLE_EXIT_REASON == "cycle_target"
    assert CYCLE_EXIT_REASON != LabService.MANUAL_EXIT_REASON
