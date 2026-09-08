"""SOCIAL — the first signal on this platform that is not a price.

Twelve experiments have now varied liquidity, momentum, flow, size, hold time
and take-profit. Every one of those is a property of the MARKET, and the
measured payoff space says the market's own numbers do not carry an edge here
at any exit level. This registry reads how many people are COMMENTING on a
coin, which none of them could see.

The tests below defend two things, and profit is neither of them:

* the pair is a CONTROLLED comparison — one condition apart, nothing else;
* the rule cannot fire on a number it has not actually measured.

The second is the one that would silently ruin the experiment. `reply_count`
is cumulative, so a single reading measures a coin's AGE more than its
interest; velocity needs two readings and is absent until it has them. If an
absent feature ever read as zero-or-passing, `SOC-01` would degenerate into
`SOC-02` and the two wallets would be the same experiment run twice.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from app.compound.service import CompoundService
from app.lab.service import LabService
from app.models.lab import LabStrategy
from app.models.social import PumpfunSocialSnapshot
from app.social import spec as sspec

from tests.integration.test_lab_accounting import NOW

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------
# one condition apart
# --------------------------------------------------------------------------


def test_the_two_wallets_differ_by_exactly_one_condition() -> None:
    """The single most important assertion in this file.

    A control that also drew from a different POOL would differ in two ways at
    once and the comparison would answer nothing.
    """
    rising, control = sspec.STRATEGIES
    a = {str(c) for c in rising.entry}
    b = {str(c) for c in control.entry}
    assert b < a, "the control must be the signal MINUS one condition"
    assert len(a - b) == 1
    assert next(iter(a - b)).startswith("Condition(feature='social_reply_velocity'")


def test_nothing_but_the_entry_rule_varies() -> None:
    fixed = {
        (s.size_usd, s.max_concurrent, s.max_exposure_usd, s.checkpoint_minutes,
         s.exits.time_exit_hours, s.exits.take_profit, s.exits.stop_loss,
         s.exits.trailing_drawdown, s.exits.partial_at)
        for s in sspec.STRATEGIES
    }
    assert len(fixed) == 1


def test_the_rule_carries_no_fitted_threshold() -> None:
    """`> 0` is a DIRECTION, not a level.

    Any number chosen today would be fitted to a few hours of collection —
    which is exactly how the liq/mcap filter came to look like an 8.51 profit
    factor before split-half took it to 0.72.
    """
    velocity = [c for s in sspec.STRATEGIES for c in s.entry
                if c.feature == "social_reply_velocity"]
    assert len(velocity) == 1
    assert velocity[0].op == "gt" and velocity[0].value == D("0")


def test_it_inherits_the_ratchet_rather_than_inventing_one() -> None:
    assert sspec.CYCLE_TARGET_MULTIPLE == D("1.10")
    assert sspec.STARTING_EQUITY == D("100")
    assert sspec.SIZE_USD == D("5") and sspec.MAX_CONCURRENT == 20
    assert sspec.SIZE_USD * sspec.MAX_CONCURRENT == sspec.STARTING_EQUITY


def test_it_is_a_separate_registry_from_every_other_tournament() -> None:
    from app.compound import spec as cspec
    from app.depth import spec as dspec
    from app.lab import spec as v7
    from app.momentum import spec as mspec
    from app.pumpfun import spec as pspec

    assert len({sspec.SPEC_HASH, dspec.SPEC_HASH, cspec.SPEC_HASH,
                v7.SPEC_HASH, mspec.SPEC_HASH, pspec.SPEC_HASH}) == 6


# --------------------------------------------------------------------------
# it cannot fire on a number it has not measured
# --------------------------------------------------------------------------


def test_an_unmeasured_velocity_fails_the_rising_rule() -> None:
    """Absent must mean NO, not zero.

    If a missing feature ever passed, `SOC-01` would collapse into `SOC-02` and
    the experiment would be one wallet reported twice.
    """
    rising = sspec.BY_ID["SOC-01"]
    pool = {"is_pumpfun": D(1), "social_seen": D(1)}
    assert not all(c.evaluate(pool) for c in rising.entry)
    assert all(c.evaluate(pool) for c in sspec.BY_ID["SOC-02"].entry), (
        "the control must still take the same coin — that is the comparison"
    )
    assert all(c.evaluate({**pool, "social_reply_velocity": D("0.5")})
               for c in rising.entry)


def test_flat_and_falling_comment_rates_are_both_refused() -> None:
    rising = sspec.BY_ID["SOC-01"]
    for v in (D("0"), D("-3")):
        assert not all(c.evaluate(
            {"is_pumpfun": D(1), "social_seen": D(1), "social_reply_velocity": v}
        ) for c in rising.entry), v


def test_a_coin_outside_the_feed_is_refused_by_both(db_session) -> None:
    for s in sspec.STRATEGIES:
        assert not all(c.evaluate({"is_pumpfun": D(1), "social_seen": D(0)})
                       for c in s.entry), s.id


async def test_velocity_is_none_until_there_are_two_readings(db_session):
    """One reading of a CUMULATIVE counter says how old the coin is, not how
    much interest it is getting now."""
    svc = LabService(db_session, registry=sspec)
    mint = "SoC" + "1" * 41

    assert await svc._social(mint) == (False, None)

    db_session.add(PumpfunSocialSnapshot(
        mint_address=mint, observed_at=NOW, reply_count=400,
        source_sort="last_reply",
    ))
    await db_session.flush()
    seen, velocity = await svc._social(mint)
    assert seen is True and velocity is None, "seen, but not yet measurable"


async def test_velocity_is_replies_per_hour_over_the_two_latest_readings(db_session):
    svc = LabService(db_session, registry=sspec)
    mint = "SoC" + "2" * 41
    # An old burst that must NOT be averaged into the current rate.
    for at, count in ((NOW - timedelta(hours=6), 0),
                      (NOW - timedelta(minutes=30), 100),
                      (NOW, 110)):
        db_session.add(PumpfunSocialSnapshot(
            mint_address=mint, observed_at=at, reply_count=count,
            source_sort="last_reply",
        ))
    await db_session.flush()

    seen, velocity = await svc._social(mint)
    assert seen is True
    assert velocity == D(20), "10 replies in 30 min, not the 6-hour average"


async def test_a_falling_counter_gives_negative_velocity(db_session):
    """pump.fun can delete comments. A drop is real information and must reach
    the rule as a negative number rather than being clamped to zero."""
    svc = LabService(db_session, registry=sspec)
    mint = "SoC" + "3" * 41
    for at, count in ((NOW - timedelta(hours=1), 50), (NOW, 20)):
        db_session.add(PumpfunSocialSnapshot(
            mint_address=mint, observed_at=at, reply_count=count,
            source_sort="last_reply",
        ))
    await db_session.flush()
    assert (await svc._social(mint))[1] == D(-30)


async def test_two_readings_at_the_same_instant_do_not_divide_by_zero(db_session):
    svc = LabService(db_session, registry=sspec)
    mint = "SoC" + "4" * 41
    for count in (10, 12):
        db_session.add(PumpfunSocialSnapshot(
            mint_address=mint, observed_at=NOW, reply_count=count,
            source_sort="last_reply",
        ))
    await db_session.flush()
    assert (await svc._social(mint)) == (True, None)


# --------------------------------------------------------------------------
# it runs
# --------------------------------------------------------------------------


async def test_activation_opens_two_wallets_each_at_the_book(db_session):
    await CompoundService(db_session, registry=sspec).tick(now=NOW)
    rows = list((await db_session.execute(
        select(LabStrategy).where(LabStrategy.spec_hash == sspec.SPEC_HASH)
    )).scalars())
    assert len(rows) == 2
    assert all(r.cash == D("100") for r in rows)


async def test_each_wallet_ratchets_independently(db_session):
    svc = CompoundService(db_session, registry=sspec)
    await svc.tick(now=NOW)
    rows = list((await db_session.execute(
        select(LabStrategy).where(LabStrategy.spec_hash == sspec.SPEC_HASH)
        .order_by(LabStrategy.strategy_id)
    )).scalars())
    rows[0].cash = D("118")
    await db_session.flush()

    out = await svc.tick(now=NOW + timedelta(minutes=2))
    assert len(out["banked"]) == 1
    assert out["banked"][0]["strategy_id"] == "SOC-01"


def test_the_social_features_did_not_disturb_the_running_tournaments() -> None:
    """Adding a feature is safe BY CONSTRUCTION — SPEC_HASH is taken over the
    STRATEGIES, never over the feature builder — and this pins it.

    It matters because the alternative is not a failed test but a halted
    experiment: a registry whose hash moves stops on `spec_hash_drift`, and
    V7 has been running since 2026-09-04.
    """
    from app.lab import spec as v7
    assert v7.SPEC_HASH == (
        "ae1627b4ec0d3f9f4202e874333582f0deba1e306068a6401e7c9bf6a396f70c")


def test_the_registry_is_frozen() -> None:
    assert sspec.SPEC_HASH == (
        "ce5adc69fcec0cac04a58e0411a7c39be4661ed81030839b181fdc2802fb5a33")
    assert sspec.SPEC_VERSION == "social-1.0.0"


# --------------------------------------------------------------------------
# the board must not imply a ranking
# --------------------------------------------------------------------------


async def test_the_board_reads_signal_then_control_whoever_is_winning(db_session):
    """A comparison sorted by outcome is read as a leaderboard.

    The Depth curve had the same requirement for the opposite reason, and it is
    the whole justification for `order` being the caller's business: this pair
    means nothing as a ranking, and a page that floats today's winner to the
    top invites exactly that misreading.
    """
    from app.social.api import board

    svc = CompoundService(db_session, registry=sspec)
    await svc.tick(now=NOW)
    rows = list((await db_session.execute(
        select(LabStrategy).where(LabStrategy.spec_hash == sspec.SPEC_HASH)
        .order_by(LabStrategy.strategy_id)
    )).scalars())
    # Put the CONTROL far ahead; a leaderboard would float it to the top.
    rows[1].cash = D("190")
    await db_session.flush()

    out = await board(db_session)
    assert [w["strategy_id"] for w in out["wallets"]] == ["SOC-01", "SOC-02"]
    assert [w["is_control"] for w in out["wallets"]] == [False, True]


async def test_the_board_carries_the_rules_it_is_testing(db_session):
    """Without the rule beside the number the board is two equities and no
    experiment."""
    from app.social.api import board

    await CompoundService(db_session, registry=sspec).tick(now=NOW)
    out = await board(db_session)
    rising, control = out["wallets"]
    assert len(rising["entry_text"]) == len(control["entry_text"]) + 1
    assert any("comment" in t.lower() or "social" in t.lower()
               for t in rising["entry_text"])
    assert all(w["exit_text"] for w in out["wallets"])


async def test_an_unactivated_board_says_so_rather_than_reporting_zeros(db_session):
    from app.social.api import board

    out = await board(db_session)
    assert out["activated"] is False
    assert out["spec_version"] == sspec.SPEC_VERSION


# --------------------------------------------------------------------------
# stopping one lab must not stop the others
# --------------------------------------------------------------------------


def test_every_lab_has_a_switch_of_its_own() -> None:
    """`FEATURE_LAB_ENABLED` is the master, and for a long time it was ALSO
    V7's only switch — so "stop V7" and "stop every experiment here" were the
    same action, which is why V7 kept trading through two tournaments that were
    supposed to have replaced it."""
    from app.core.config import settings

    for flag in ("FEATURE_V7_LAB_ENABLED", "FEATURE_COMPOUND_LAB_ENABLED",
                 "FEATURE_MOMENTUM_LAB_ENABLED", "FEATURE_DEPTH_LAB_ENABLED",
                 "FEATURE_PUMPFUN_LAB_ENABLED", "FEATURE_SOCIAL_LAB_ENABLED"):
        assert hasattr(settings, flag), flag
    # Defaults True: turning an existing deployment's V7 off must be a
    # deliberate act, never a side effect of shipping the flag.
    assert settings.FEATURE_V7_LAB_ENABLED is True


async def test_a_stopped_v7_still_settles_what_it_is_holding(monkeypatch):
    """Stopping an experiment means it opens nothing MORE.

    Gating the whole tick would leave open positions never closing and the
    final equity marked at whatever the last tick happened to see — a frozen
    book reported as a result. That is worse than leaving it running, because
    it looks finished.

    `_lab_tick` swallows its own exceptions by design, so a broken gate here
    would show up as a silent `{"failed": True}` rather than a stack trace.
    The assertions therefore check the CALLS, not just the return.
    """
    from contextlib import asynccontextmanager

    from app.core.config import settings
    from app.lab import scheduler

    monkeypatch.setattr(settings, "FEATURE_LAB_ENABLED", True)
    monkeypatch.setattr(settings, "FEATURE_V7_LAB_ENABLED", False)
    calls: list[str] = []

    class FakeSession:
        async def scalar(self, *a, **k):
            return True  # the advisory lock is ours

        async def commit(self):
            calls.append("commit")

        async def rollback(self): ...

    @asynccontextmanager
    async def fake_factory():
        yield FakeSession()

    class Tournament:
        id = uuid.uuid4()
        valid_from = NOW
        snapshot_taken_at = NOW

    class Spy:
        def __init__(self, *a, **k): ...

        async def activate(self, **k):
            calls.append("activate")
            return Tournament()

        async def evaluate_due(self, **k):
            calls.append("evaluate_due")
            return 0

        async def settle(self, **k):
            calls.append("settle")
            return 0

        async def record_equity(self, **k):
            calls.append("record_equity")

    async def no_snapshots(*a, **k):
        return []

    monkeypatch.setattr(scheduler, "SessionFactory", fake_factory)
    monkeypatch.setattr(scheduler, "LabService", Spy)
    monkeypatch.setattr(scheduler, "_snapshots", no_snapshots)

    out = await scheduler._lab_tick()

    assert out.get("failed") is not True, out
    assert "evaluate_due" not in calls, "a stopped lab must open nothing"
    assert "settle" in calls and "record_equity" in calls, calls
    assert out["decided"] == "stopped"


async def test_v7_still_opens_positions_while_its_switch_is_on(monkeypatch):
    """The other half of the gate — a flag that stops everything is not a
    switch, it is an outage."""
    from contextlib import asynccontextmanager

    from app.core.config import settings
    from app.lab import scheduler

    monkeypatch.setattr(settings, "FEATURE_LAB_ENABLED", True)
    monkeypatch.setattr(settings, "FEATURE_V7_LAB_ENABLED", True)
    calls: list[str] = []

    class FakeSession:
        async def scalar(self, *a, **k):
            return True

        async def commit(self): ...

        async def rollback(self): ...

    @asynccontextmanager
    async def fake_factory():
        yield FakeSession()

    class Tournament:
        id = uuid.uuid4()
        valid_from = NOW
        snapshot_taken_at = NOW

    class Spy:
        def __init__(self, *a, **k): ...

        async def activate(self, **k):
            return Tournament()

        async def evaluate_due(self, **k):
            calls.append("evaluate_due")
            return 3

        async def settle(self, **k):
            return 0

        async def record_equity(self, **k): ...

    async def no_snapshots(*a, **k):
        return []

    monkeypatch.setattr(scheduler, "SessionFactory", fake_factory)
    monkeypatch.setattr(scheduler, "LabService", Spy)
    monkeypatch.setattr(scheduler, "_snapshots", no_snapshots)

    out = await scheduler._lab_tick()
    assert "evaluate_due" in calls
    assert out["decided"] == 3
