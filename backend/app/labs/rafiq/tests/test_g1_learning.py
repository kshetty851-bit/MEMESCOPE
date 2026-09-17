"""G1's learning layer, wired: what it hears, when, and what it changes.

`g1/test_learning.py` proves `learning.py` refuses to learn from noise. These
prove the runner feeds it every closed trade exactly once, only after the hour
that follows the exit, and that what it learns reaches the next entry and
survives a restart.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.labs.rafiq import outcomes, registry
from app.labs.rafiq.g1 import learning
from app.labs.rafiq.g1 import strategy_G1 as g1
from app.labs.rafiq.models import (
    RafiqLabAdjustment,
    RafiqLabPosition,
    RafiqLabRunState,
)
from app.labs.rafiq.service import RafiqLabService
from app.labs.rafiq.tests.test_g1_engine import DEEP, g1_book, path, seed_path
from app.models.market import TradingStatus

NOW = datetime(2026, 9, 17, 18, 0, tzinfo=UTC)


async def closed_trade(session, book, tag: str, *, reason: str, closed_at: datetime,
                       after: list, scaled_out: bool = False,
                       exit_price: Decimal = Decimal(1)) -> RafiqLabPosition:
    """A closed G1 position whose token printed `after` from its exit on."""
    mint = await seed_path(session, tag, closed_at, after)
    pos = RafiqLabPosition(
        strategy_id=book.id, lab_run_id=book.lab_run_id, mint_address=mint, leg=1,
        opened_at=closed_at - timedelta(minutes=20), entry_price=Decimal(1),
        entry_observed_price=Decimal(1), quantity=Decimal(10), cost_basis=Decimal(10),
        entry_liquidity_usd=DEEP, stop_price=Decimal("0.88"), stop_pct=Decimal(12),
        trailing_frac=g1.RUNNER_TRAIL, max_hold_seconds=2700, status="closed",
        peak_price=Decimal(1), last_mark_price=exit_price, last_evaluated_at=closed_at,
        closed_at=closed_at, exit_price=exit_price, exit_observed_price=exit_price,
        exit_proceeds_usd=Decimal(10) * exit_price, exit_reason=reason,
        scaled_out=scaled_out, fraction_open=Decimal("0.25") if scaled_out else Decimal(1),
        realised_usd=Decimal(0), abandon_gain=g1.ABANDON_UNLESS_GAIN,
        size_multiplier=Decimal(1))
    session.add(pos)
    await session.flush()
    return pos


async def state(session) -> RafiqLabRunState:
    return (await session.execute(
        select(RafiqLabRunState).where(RafiqLabRunState.lab_run_id == registry.G1_RUN)
        .execution_options(populate_existing=True)
    )).scalars().one()


#: An hour that runs: +50% within the hour, pool alive throughout.
RAN = path((0, 1), (20, "1.5"), (40, "1.2"), length=70)
#: An hour that stays quiet and alive.
QUIET = path((0, 1), length=70)
#: An hour in which the pool dies.
DIED = path((0, 1), status_from=5, length=70)


@pytest.mark.integration
async def test_an_adjustment_learned_is_the_one_the_next_entry_uses(
    lab_session, monkeypatch
) -> None:
    """The gate. Forty trades whose hours have closed: every abandoned token
    ran afterwards, no held token died. `learning.py` loosens the threshold
    one step, the adjustment is stored with its evidence, and the entry made
    in the same tick is frozen with the NEW threshold."""
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    service = RafiqLabService(lab_session)
    await service.activate(now=NOW - timedelta(days=1))
    book = await g1_book(lab_session)
    for i in range(20):
        at = NOW - timedelta(hours=3) + timedelta(minutes=2 * i)
        await closed_trade(lab_session, book, f"cut{i}", reason=g1.Exit.ABANDON,
                           closed_at=at, after=RAN)
        await closed_trade(lab_session, book, f"kept{i}", reason=g1.Exit.MAX_HOLD,
                           closed_at=at + timedelta(minutes=1), after=QUIET)
    fresh = await seed_path(lab_session, "nextentry", NOW, path((0, 1), length=5))

    result = await service.tick(now=NOW)

    assert result["learned"] == 40
    made = list((await lab_session.execute(
        select(RafiqLabAdjustment).where(
            RafiqLabAdjustment.lab_run_id == registry.G1_RUN,
            RafiqLabAdjustment.parameter == "abandon_gain_threshold")
    )).scalars())
    assert len(made) == 1
    adj = made[0]
    assert (adj.old_value, adj.new_value) == (Decimal("0.08"), Decimal("0.09"))
    assert adj.sample_size == learning.MIN_SAMPLE
    assert adj.z_score >= Decimal(str(learning.SIGNIFICANCE_Z))
    assert "cutting winners" in adj.reason

    entered = (await lab_session.execute(
        select(RafiqLabPosition).where(RafiqLabPosition.mint_address == fresh)
    )).scalars().one()
    assert entered.abandon_gain == Decimal("0.09"), \
        "the entry did not use the threshold learning had just moved"

    saved = (await state(lab_session)).learning
    assert saved["gain_threshold"] == "0.09"
    assert saved["abandoned"] == [] and saved["held"] == [], "evidence not cleared"
    assert len(saved["regime_recent"]) == 40

    # A restart reads the same threshold and the same audit trail.
    reborn = RafiqLabService(lab_session)
    assert (await reborn._g1_parameters(book, now=NOW))[0] == Decimal("0.09")
    lrn, _ = await reborn._learner(book)
    assert lrn.current_parameters()["adjustments_made"] == 1


@pytest.mark.integration
async def test_a_trade_is_learned_once_and_only_after_its_hour(
    lab_session, monkeypatch
) -> None:
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    service = RafiqLabService(lab_session)
    await service.activate(now=NOW - timedelta(days=1))
    book = await g1_book(lab_session)
    early = await closed_trade(lab_session, book, "early", reason=g1.Exit.STOP,
                               closed_at=NOW - timedelta(minutes=61), after=DIED,
                               exit_price=Decimal("0.5"))
    young = await closed_trade(lab_session, book, "young", reason=g1.Exit.STOP,
                               closed_at=NOW - timedelta(minutes=30), after=QUIET)

    assert (await service.tick(now=NOW))["learned"] == 1
    assert (await service.tick(now=NOW + timedelta(minutes=1)))["learned"] == 0

    await lab_session.refresh(early)
    await lab_session.refresh(young)
    assert early.learning_recorded_at == NOW
    assert early.forward_went_to_zero is True
    assert early.forward_peak_multiple == Decimal("1.000000")
    assert young.learning_recorded_at is None and young.forward_peak_multiple is None
    saved = (await state(lab_session)).learning
    assert saved["held"] == [True] and saved["abandoned"] == []

    # Its hour closes; it is heard once more — itself, not a repeat.
    assert (await service.tick(now=NOW + timedelta(minutes=31)))["learned"] == 1
    saved = (await state(lab_session)).learning
    assert saved["held"] == [True, False]


@pytest.mark.integration
async def test_every_exit_path_reaches_the_learner(lab_session, monkeypatch) -> None:
    """Abandoned trades go to one bucket, everything else to the other, and
    a scale-out is what counts as reaching the take-profit rung."""
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    service = RafiqLabService(lab_session)
    await service.activate(now=NOW - timedelta(days=1))
    book = await g1_book(lab_session)
    start = NOW - timedelta(hours=2)
    for k, (reason, after, scaled) in enumerate([
        (g1.Exit.ABANDON, RAN, False),
        (g1.Exit.STOP, DIED, False),
        (g1.Exit.RUNNER_TRAIL, QUIET, True),
        (g1.Exit.MAX_HOLD, QUIET, True),
        (g1.Exit.ABANDON, QUIET, False),
    ]):
        await closed_trade(lab_session, book, f"path{k}", reason=reason,
                           closed_at=start + timedelta(minutes=k), after=after,
                           scaled_out=scaled)

    assert (await service.tick(now=NOW))["learned"] == 5

    saved = (await state(lab_session)).learning
    assert saved["abandoned"] == [True, False]        # ran afterwards, did not
    assert saved["held"] == [True, False, False]      # stop died; the rest lived
    assert saved["regime_recent"] == [False, False, True, True, False]


@pytest.mark.integration
async def test_a_halved_regime_halves_the_next_bet(lab_session, monkeypatch) -> None:
    """The regime monitor's multiplier reaches sizing, and the change is
    audited like any other parameter the run moved."""
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    service = RafiqLabService(lab_session)
    await service.activate(now=NOW - timedelta(days=1))
    book = await g1_book(lab_session)
    run_state = await service._run_state(book)
    # A trailing 40% runner rate, and the last 120 closed trades had none.
    run_state.learning = {
        "gain_threshold": "0.08", "abandoned": [], "held": [],
        "regime_recent": [False] * learning.REGIME_WINDOW,
        "regime_baseline": 0.40, "size_multiplier": 1.0}
    await lab_session.flush()
    mint = await seed_path(lab_session, "halved", NOW, path((0, 1), length=5))

    await service.tick(now=NOW)

    row = (await lab_session.execute(
        select(RafiqLabPosition).where(RafiqLabPosition.mint_address == mint)
    )).scalars().one()
    assert row.size_multiplier == Decimal("0.5")
    assert row.cost_basis == g1.position_size(Decimal(1000)) * Decimal("0.5") \
        == Decimal("5.00")
    moved = (await lab_session.execute(
        select(RafiqLabAdjustment).where(RafiqLabAdjustment.parameter == "size_multiplier")
    )).scalars().one()
    assert (moved.old_value, moved.new_value) == (Decimal(1), Decimal("0.5"))
    assert "tail is not there" in moved.reason
    assert (await state(lab_session)).learning["size_multiplier"] == 0.5


def test_the_hour_after_exit_reads_the_pool_not_its_leftover_price() -> None:
    """`exit_outcome` without a database."""
    end = NOW + outcomes.EXIT_WINDOW

    def mark(minute, price, liquidity=DEEP, status=TradingStatus.TRADING):
        return SimpleNamespace(captured_at=NOW + timedelta(minutes=minute),
                               price_usd=Decimal(str(price)), liquidity_usd=liquidity,
                               trading_status=status)

    one = Decimal(1)
    live = [mark(5, "1.4"), mark(30, "1.1")]
    assert outcomes.exit_outcome(live, entry_price=one, exit_price=one, end=end,
                                 delisted_at=None) == (Decimal("1.4"), False)
    # A drained pool still printing 5x is not a run, and it is a death.
    dead = [mark(5, "1.1"), mark(20, 5, Decimal(0), TradingStatus.INACTIVE)]
    assert outcomes.exit_outcome(dead, entry_price=one, exit_price=one, end=end,
                                 delisted_at=None) == (Decimal("1.1"), True)
    # Nothing printed at all: no peak, and no pool.
    assert outcomes.exit_outcome([], entry_price=one, exit_price=one, end=end,
                                 delisted_at=None) == (None, True)
    # The exit itself found no pool.
    assert outcomes.exit_outcome(live, entry_price=one, exit_price=Decimal(0), end=end,
                                 delisted_at=None)[1] is True
    # Alive, but at a tenth of entry.
    crushed = [mark(10, "0.09")]
    assert outcomes.exit_outcome(crushed, entry_price=one, exit_price=one, end=end,
                                 delisted_at=None)[1] is True
    # Delisted after its last print, inside the hour.
    assert outcomes.exit_outcome(live, entry_price=one, exit_price=one, end=end,
                                 delisted_at=NOW + timedelta(minutes=40))[1] is True


async def test_the_learning_task_is_inert_while_the_flag_is_off(monkeypatch) -> None:
    from app.labs.rafiq.scheduler import learn
    from app.workers.celery_app import celery_app

    monkeypatch.delenv("RAFIQ_LAB_ENABLED", raising=False)
    assert await learn() == {"skipped": "rafiq_lab_disabled"}
    celery_app.loader.import_default_modules()
    assert "app.labs.rafiq.scheduler.rafiq_g1_learning_tick" in celery_app.tasks
