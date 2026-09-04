"""Momentum V2: twenty pump.fun wallets, each ratcheting at +10%.

Two properties carry this experiment, and neither is the P&L.

**The grid must be complete and attributable.** Three momentum rules against
six liquidity floors, so a winning cell can be told apart from a winning row or
column. A hand-picked set of twenty thresholds cannot make that distinction,
which is how the mcap filter looked like an 8.51 profit factor until split-half
took it to 0.72.

**The controls must live inside the twenty.** Every no-edge finding here was
produced by a control rather than by a strategy, and the random arm has beaten
the designed ones twice. Eighteen momentum cells with nothing beside them
produce a leaderboard where the top wallet always looks good.

And the constraint the owner added late: pump.fun tokens ONLY, controls
included — a control free to buy outside the universe under test would confound
the pool with the rule.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from app.compound.service import CompoundService
from app.lab import spec as v7spec
from app.models.compound import CompoundCycle
from app.models.lab import LabStrategy
from app.momentum import spec as mspec

from tests.integration.test_lab_accounting import NOW, VALID_FROM

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------
# shape
# --------------------------------------------------------------------------


def test_it_is_a_complete_grid_plus_two_controls() -> None:
    assert len(mspec.STRATEGIES) == 20
    assert len(mspec._MOMENTUM) * len(mspec._LIQUIDITY) == 18
    controls = [s for s in mspec.STRATEGIES if s.evidence == "CONTROL"]
    assert len(controls) == 2


def test_every_momentum_rule_appears_at_every_liquidity_floor() -> None:
    """A missing cell becomes a silent conclusion: a rule absent at $1M reads
    as a rule that does not work at $1M, when nobody ran it."""
    grid = [s for s in mspec.STRATEGIES if s.evidence != "CONTROL"]
    seen = set()
    for s in grid:
        liq = next(c.value for c in s.entry if c.feature == "liq")
        mom = tuple(sorted(c.feature for c in s.entry
                           if c.feature not in ("liq", "is_pumpfun")))
        seen.add((mom, liq))
    expected = {
        (tuple(sorted(c.feature for c in conds)), floor)
        for _k, _t, conds in mspec._MOMENTUM
        for floor in mspec._LIQUIDITY
    }
    assert seen == expected


def test_only_the_liquidity_floor_varies_within_a_momentum_rule() -> None:
    """Otherwise a difference down a column is unattributable."""
    by_rule: dict[tuple, list] = {}
    for s in mspec.STRATEGIES:
        if s.evidence == "CONTROL":
            continue
        key = tuple(sorted(c.feature for c in s.entry if c.feature != "liq"))
        by_rule.setdefault(key, []).append(s)
    for key, arms in by_rule.items():
        assert len(arms) == len(mspec._LIQUIDITY), key
        fixed = {(a.size_usd, a.max_concurrent, a.checkpoint_minutes,
                  a.exits.time_exit_hours, a.exits.take_profit) for a in arms}
        assert len(fixed) == 1, f"more than the floor varies within {key}"


# --------------------------------------------------------------------------
# the constraint added last
# --------------------------------------------------------------------------


def test_every_wallet_including_the_controls_is_pumpfun_only() -> None:
    for s in mspec.STRATEGIES:
        assert any(c.feature == "is_pumpfun" for c in s.entry), s.id


def test_the_provenance_feature_matches_what_discovery_admitted() -> None:
    """`is_pumpfun` must be derived from the SAME program list the scanner
    listens to, or the filter and the universe drift apart."""
    from app.core.config import settings
    from app.lab.service import LabService

    assert LabService._pumpfun_programs() == set(settings.SCANNER_WATCH_PROGRAMS)
    assert "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P" in LabService._pumpfun_programs()


# --------------------------------------------------------------------------
# the ratchet, across twenty wallets
# --------------------------------------------------------------------------


def test_it_is_a_separate_registry_from_every_other_tournament() -> None:
    from app.compound import spec as cspec
    from app.pumpfun import spec as pspec

    hashes = {mspec.SPEC_HASH, cspec.SPEC_HASH, v7spec.SPEC_HASH, pspec.SPEC_HASH}
    assert len(hashes) == 4


async def test_activation_opens_twenty_wallets_each_at_the_book(db_session):
    await CompoundService(db_session, registry=mspec).tick(now=NOW)
    rows = list((await db_session.execute(
        select(LabStrategy).where(LabStrategy.spec_hash == mspec.SPEC_HASH)
    )).scalars())
    assert len(rows) == 20
    assert all(r.cash == mspec.STARTING_EQUITY for r in rows)


async def test_every_wallet_gets_its_own_first_cycle(db_session):
    """Twenty independent ratchets, not one shared."""
    svc = CompoundService(db_session, registry=mspec)
    await svc.tick(now=NOW)
    cycles = list((await db_session.execute(select(CompoundCycle))).scalars())
    assert len(cycles) == 20
    assert {c.cycle_no for c in cycles} == {1}
    assert all(c.base_usd == D("100") and c.target_usd == D("110") for c in cycles)


async def test_one_wallet_banking_does_not_move_the_others(db_session):
    """The property that makes twenty ratchets twenty experiments."""
    svc = CompoundService(db_session, registry=mspec)
    await svc.tick(now=NOW)
    rows = list((await db_session.execute(
        select(LabStrategy).where(LabStrategy.spec_hash == mspec.SPEC_HASH)
        .order_by(LabStrategy.strategy_id)
    )).scalars())
    winner = rows[0]
    winner.cash = D("115")
    await db_session.flush()

    out = await svc.tick(now=NOW + timedelta(minutes=2))
    assert len(out["banked"]) == 1
    assert out["banked"][0]["strategy_id"] == winner.strategy_id

    cycles = list((await db_session.execute(
        select(CompoundCycle).order_by(CompoundCycle.cycle_no)
    )).scalars())
    banked = [c for c in cycles if c.reached_at is not None]
    assert len(banked) == 1
    assert banked[0].strategy_row_id == winner.id
    # Everyone else is still on cycle 1 at the original base.
    others = [c for c in cycles if c.strategy_row_id != winner.id]
    assert all(c.reached_at is None and c.base_usd == D("100") for c in others)
    assert len([c for c in cycles if c.strategy_row_id == winner.id]) == 2
