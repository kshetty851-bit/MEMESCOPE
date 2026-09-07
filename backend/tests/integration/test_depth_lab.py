"""The depth curve — twenty wallets that must differ in exactly one number.

This experiment exists because ten previous ones failed the same way: designed
entry rules lost, and in three of them a RANDOM control beat them. Momentum V2
was the clearest — its winner was `RANDOM-CONTROL-1M` at $126.50, ahead of all
eighteen momentum arms, while its identical twin at $300k went to zero. Same
rule, same ratchet, same size; only the floor differed.

So the property under test here is not profit. It is that **nothing except the
floor varies**, because a dose-response curve with a second moving part is not
a curve, it is two effects added together. If a single cell acquired an extra
condition the whole experiment would silently stop answering its question, and
that is the failure these tests exist to prevent.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from app.compound.service import CompoundService
from app.depth import spec as dspec
from app.models.compound import CompoundCycle
from app.models.lab import LabStrategy

from tests.integration.test_lab_accounting import NOW

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------
# one variable
# --------------------------------------------------------------------------


def test_nothing_but_the_liquidity_floor_varies() -> None:
    """The single most important assertion in this file."""
    fixed = {
        (s.size_usd, s.max_concurrent, s.max_exposure_usd, s.checkpoint_minutes,
         s.exits.time_exit_hours, s.exits.take_profit, s.exits.stop_loss,
         s.exits.trailing_drawdown, s.exits.partial_at)
        for s in dspec.STRATEGIES
    }
    assert len(fixed) == 1, "a second moving part turns the curve into two effects"


def test_no_wallet_carries_a_condition_beyond_the_floor() -> None:
    """No momentum, no score, no flow filter. That absence IS the experiment —
    ten registries have now varied selection and none of them moved the
    outcome."""
    for s in dspec.STRATEGIES:
        assert {c.feature for c in s.entry} == {"is_pumpfun", "liq"}, s.id
        assert len(s.entry) == 2, s.id


def test_the_floors_are_distinct_and_ordered() -> None:
    floors = [next(c.value for c in s.entry if c.feature == "liq")
              for s in dspec.STRATEGIES]
    assert floors == sorted(floors), "the ladder must read in order"
    assert len(set(floors)) == 20


def test_the_ladder_stops_where_the_population_does() -> None:
    """Measured over the three days to 2026-09-07: 806 pump.fun tokens above
    $100k, 291 above $250k, 29 above $500k and TEN above $1M. Floors above $1M
    were the obvious design and would have produced wallets with nothing to
    buy — the cells would read as "depth does not work up here" when nobody
    could have traded there."""
    floors = [int(next(c.value for c in s.entry if c.feature == "liq"))
              for s in dspec.STRATEGIES]
    assert max(floors) == 1_000_000
    assert min(floors) == 25_000


def test_it_holds_momentum_v2_constant_so_the_two_can_be_compared() -> None:
    """A different size or horizon would confound the floor with whatever else
    moved beside it."""
    from app.momentum import spec as mspec

    d, m = dspec.STRATEGIES[0], mspec.STRATEGIES[0]
    assert (d.size_usd, d.max_concurrent, d.checkpoint_minutes,
            d.exits.time_exit_hours, d.exits.take_profit) == \
           (m.size_usd, m.max_concurrent, m.checkpoint_minutes,
            m.exits.time_exit_hours, m.exits.take_profit)
    assert dspec.CYCLE_TARGET_MULTIPLE == mspec.CYCLE_TARGET_MULTIPLE
    assert dspec.STARTING_EQUITY == mspec.STARTING_EQUITY


def test_it_is_a_separate_registry_from_every_other_tournament() -> None:
    from app.compound import spec as cspec
    from app.lab import spec as v7
    from app.momentum import spec as mspec
    from app.pumpfun import spec as pspec

    assert len({dspec.SPEC_HASH, cspec.SPEC_HASH, v7.SPEC_HASH,
                mspec.SPEC_HASH, pspec.SPEC_HASH}) == 5


# --------------------------------------------------------------------------
# it runs
# --------------------------------------------------------------------------


async def test_activation_opens_twenty_wallets_each_at_the_book(db_session):
    await CompoundService(db_session, registry=dspec).tick(now=NOW)
    rows = list((await db_session.execute(
        select(LabStrategy).where(LabStrategy.spec_hash == dspec.SPEC_HASH)
    )).scalars())
    assert len(rows) == 20
    assert all(r.cash == D("100") for r in rows)


async def test_each_cell_ratchets_independently(db_session):
    """Twenty cells on one curve, not one wallet reported twenty ways."""
    svc = CompoundService(db_session, registry=dspec)
    await svc.tick(now=NOW)
    rows = list((await db_session.execute(
        select(LabStrategy).where(LabStrategy.spec_hash == dspec.SPEC_HASH)
        .order_by(LabStrategy.strategy_id)
    )).scalars())
    rows[11].cash = D("118")
    await db_session.flush()

    out = await svc.tick(now=NOW + timedelta(minutes=2))
    assert len(out["banked"]) == 1
    assert out["banked"][0]["strategy_id"] == rows[11].strategy_id

    cycles = list((await db_session.execute(select(CompoundCycle))).scalars())
    assert len([c for c in cycles if c.reached_at is not None]) == 1
    assert all(c.base_usd == D("100")
               for c in cycles if c.strategy_row_id != rows[11].id)


async def test_the_board_is_ordered_by_floor_not_by_outcome(db_session):
    """A curve sorted by result is not a curve.

    The payload was derived from Momentum V2's, which ranks by equity because
    it IS a leaderboard. Here that would put the winning cell at the top and
    destroy the only thing the experiment measures — whether equity moves
    monotonically WITH depth.
    """
    from app.depth.api import board

    svc = CompoundService(db_session, registry=dspec)
    await svc.tick(now=NOW)
    rows = list((await db_session.execute(
        select(LabStrategy).where(LabStrategy.spec_hash == dspec.SPEC_HASH)
        .order_by(LabStrategy.strategy_id)
    )).scalars())
    # Make a MIDDLE cell the richest; a leaderboard would float it to the top.
    rows[9].cash = D("175")
    await db_session.flush()

    out = await board(db_session)
    assert len(out["wallets"]) == 20
    floors = [w["floor_usd"] for w in out["wallets"]]
    assert floors == sorted(floors), "the curve must read low floor to high"
    assert floors[0] == 25_000 and floors[-1] == 1_000_000
    # The rich middle cell stayed in the middle.
    richest = max(out["wallets"], key=lambda w: float(w["equity"]))
    assert out["wallets"].index(richest) not in (0, 19)


async def test_every_cell_reports_the_floor_it_is_testing(db_session):
    """Without the floor on the row there is no x-axis and no curve."""
    from app.depth.api import board

    await CompoundService(db_session, registry=dspec).tick(now=NOW)
    out = await board(db_session)
    assert all(w["floor_usd"] > 0 for w in out["wallets"])
    assert len({w["floor_usd"] for w in out["wallets"]}) == 20
