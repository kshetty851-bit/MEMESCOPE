"""G1 through the ENGINE: `RafiqLabService.tick`, a database, and price paths.

`g1/test_strategy_G1.py` proves what `strategy_G1.evaluate` says about one
price. These prove what the runner DOES with it: that a partial sale is sold,
booked and left open, that every exit reason reaches the row verbatim, that
the proceeds are the pool's, and that the ratchet stops entries without
touching what is open.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, update

from app.labs.rafiq import config, registry
from app.labs.rafiq.adapters import costs
from app.labs.rafiq.g1 import learning
from app.labs.rafiq.g1 import strategy_G1 as g1
from app.labs.rafiq.models import (
    RafiqCandidate,
    RafiqLabAdjustment,
    RafiqLabDailyState,
    RafiqLabPosition,
    RafiqLabRunState,
    RafiqLabStrategy,
)
from app.labs.rafiq.service import RafiqLabService
from app.labs.rafiq.strategies.strategy_e_ensemble import DAILY_POLICY
from app.labs.rafiq.tests.test_full_cycle import (
    digest,
    seed_candidate,
    seed_existing_wallet,
)
from app.models.market import TokenMarketSnapshot, TradingStatus
from app.models.radar import RadarToken
from app.models.token import DiscoveredToken

T0 = datetime(2026, 9, 17, 10, 0, tzinfo=UTC)
DEEP = Decimal(300_000)
TOLERANCE = Decimal("0.0002")
LIVE, DEAD = TradingStatus.TRADING, TradingStatus.INACTIVE


def D(value) -> Decimal:  # noqa: N802 - reads as a literal in the paths below
    return Decimal(str(value))


def path(*points: tuple[int, object], length: int = 100, status_from: int | None = None):
    """A price per minute since entry. `points` are (minute, price) steps held
    until the next one; rows from `status_from` on read as a drained pool."""
    out, price = [], None
    steps = dict(points)
    for k in range(length):
        price = steps.get(k, price)
        dead = status_from is not None and k >= status_from
        out.append((D(price), Decimal(0) if dead else DEEP, DEAD if dead else LIVE))
    return out


# name: (price path, exit reason, exit minute, scale-out minute or None)
PATHS = {
    "win": (path((0, 1), (5, "1.32"), (6, "1.5"), (7, "1.7"), (8, 2), (10, "1.8"),
                 (11, "1.5"), (12, "1.3"), (13, "1.10")),
            g1.Exit.RUNNER_TRAIL, 13, 5),
    "winbox": (path((0, 1), (5, "1.32"), (6, "1.5")), g1.Exit.MAX_HOLD, 45, 5),
    "flat": (path((0, 1), (3, "1.02")), g1.Exit.ABANDON, 10, None),
    "stop": (path((0, 1), (1, "0.95"), (2, "0.86")), g1.Exit.STOP, 2, None),
    "held": (path((0, 1), (2, "1.05"), (5, "1.10"), (7, "1.15")), g1.Exit.MAX_HOLD, 45, None),
    "scalestop": (path((0, 1), (5, "1.32"), (6, "1.2"), (7, 1), (8, "0.85")),
                  g1.Exit.STOP, 8, 5),
    "glitch": (path((0, 1), (4, 10), (5, 1)), g1.Exit.ABANDON, 10, None),
    "scaledead": (path((0, 1), (5, "1.32"), (6, "1.4"), status_from=7),
                  g1.Exit.MAX_HOLD, 45, 5),
    "dead": (path((0, 1), status_from=2), g1.Exit.MAX_HOLD, 45, None),
}

#: (tag, path, detected at minute). Wave 1 makes money and moves the floor
#: up; wave 2 is four pools that die, which sinks marked equity under the
#: floor; wave 3 arrives while the ratchet holds entries shut.
BOOK = [
    *[(f"win{i}", "win", i) for i in range(3)],
    *[(f"winbox{i}", "winbox", i + 1) for i in range(2)],
    *[(f"flat{i}", "flat", i + 2) for i in range(3)],
    *[(f"stop{i}", "stop", i) for i in range(3)],
    *[(f"held{i}", "held", i + 1) for i in range(3)],
    *[(f"scalestop{i}", "scalestop", i + 2) for i in range(2)],
    ("glitch0", "glitch", 3),
    ("scaledead0", "scaledead", 4),
    *[(f"dead{i}", "dead", 50) for i in range(4)],
]
BLOCKED = [("late0", 60), ("late1", 61)]


async def seed_path(session, tag: str, detected: datetime, rows) -> str:
    """A Radar admission at `detected` with one snapshot a minute along `rows`."""
    mint = ("G1" + tag + "X").ljust(44, "5")[:44]   # X ends the tag: cut1 != cut15
    token = DiscoveredToken(
        id=uuid.uuid4(), mint_address=mint, symbol=tag[:10].upper(), name=tag,
        signature=("sig" + uuid.uuid4().hex).ljust(64, "6")[:64], slot=1,
        discovered_at=detected - timedelta(minutes=1))
    session.add(token)
    await session.flush()
    session.add(RadarToken(
        token_id=token.id, mint_address=mint, first_detected_at=detected,
        first_opportunity_score=Decimal(85), first_confidence=Decimal(80),
        detection_reason=["test"], category="admission",
        current_opportunity_score=Decimal(85), current_confidence=Decimal(80),
        current_category="admission", is_active=True, model_version="test",
        last_evaluated_at=detected))
    for k, (price, liquidity, status) in enumerate(rows):
        session.add(TokenMarketSnapshot(
            token_id=token.id, mint_address=mint,
            captured_at=detected + timedelta(minutes=k),
            price_usd=price, liquidity_usd=liquidity,
            market_cap=Decimal(2_000_000), volume_5m=Decimal(5_000),
            trading_status=status, provider="test",
            pool_address=("Pool" + tag).ljust(44, "3")[:44]))
    await session.flush()
    return mint


#: The current run's books, in registry order.
CURRENT_BOOKS = ["A2", "B2", "C2", "D2", "E2", "G1"]


async def g1_book(session) -> RafiqLabStrategy:
    return (await session.execute(
        select(RafiqLabStrategy).where(RafiqLabStrategy.lab_run_id == registry.G1_RUN,
                                       RafiqLabStrategy.code == "G1")
    )).scalars().one()


async def g1_row(session, model, mint: str):
    """G1's own row for `mint`: A2-E2 trade the same admissions in its run."""
    book = await g1_book(session)
    return (await session.execute(
        select(model).where(model.strategy_id == book.id, model.mint_address == mint)
    )).scalars().one()


def expected_proceeds(row: RafiqLabPosition, rows, exit_k: int,
                      scale_k: int | None) -> Decimal:
    """The pool's answer, computed from the path rather than read off the row."""
    def reading(k):
        price, liquidity, status = rows[k]
        return price, (liquidity if status == LIVE else None)

    total, held = Decimal(0), row.quantity
    if scale_k is not None:
        price, liquidity = reading(scale_k)
        fill = min(price, row.entry_price * g1.SCALE_OUT_AT * config.FILL_DRIFT_CAP)
        total += costs.sell_proceeds(row.quantity * g1.SCALE_OUT_FRACTION, fill, liquidity)
        held = row.quantity * (1 - g1.SCALE_OUT_FRACTION)
    price, liquidity = reading(exit_k)
    if rows[exit_k][2] == DEAD:
        return total                     # a dead pool pays nothing
    return total + costs.sell_proceeds(held, price, liquidity)


@pytest.mark.integration
async def test_a_replayed_book_books_every_exit_path(lab_session, monkeypatch) -> None:
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    service = RafiqLabService(lab_session)
    await service.activate(now=T0 - timedelta(minutes=1))
    mints = {}
    for tag, name, minute in BOOK:
        mints[tag] = await seed_path(lab_session, tag, T0 + timedelta(minutes=minute),
                                     PATHS[name][0])
    for tag, minute in BLOCKED:
        mints[tag] = await seed_path(lab_session, tag, T0 + timedelta(minutes=minute),
                                     path((0, 1), length=40))

    for minute in range(0, 101):
        await service.tick(now=T0 + timedelta(minutes=minute))

    book = await g1_book(lab_session)
    rows = {r.mint_address: r for r in (await lab_session.execute(
        select(RafiqLabPosition).where(RafiqLabPosition.strategy_id == book.id)
    )).scalars()}

    # ---- every trade, its reason, its minute and its money --------------------
    assert len(BOOK) >= 20
    for tag, name, minute in BOOK:
        prices, reason, exit_k, scale_k = PATHS[name]
        row = rows.get(mints[tag])
        assert row is not None, f"{tag} was never entered"
        entered = T0 + timedelta(minutes=minute)
        assert row.opened_at == entered, tag
        assert row.status == "closed", f"{tag} still open"
        assert row.exit_reason == reason, (tag, row.exit_reason, row.exit_evidence)
        assert row.closed_at == entered + timedelta(minutes=exit_k), (tag, row.closed_at)
        assert row.scaled_out is (scale_k is not None), tag
        if scale_k is not None:
            assert row.scaled_out_at == entered + timedelta(minutes=scale_k), tag
            assert row.fraction_open == Decimal("0.25"), tag
            assert row.realised_usd > 0, tag
        else:
            assert row.fraction_open == Decimal(1) and row.realised_usd == 0, tag
        want = expected_proceeds(row, prices, exit_k, scale_k)
        # Stored at 4dp, and a partial sale is rounded once more on the way.
        assert abs(row.exit_proceeds_usd - want) <= TOLERANCE, (
            tag, row.exit_proceeds_usd, want)
        # Entry bookkeeping: bought through the same model, frozen as G1's.
        assert row.quantity == costs.buy_quantity(
            row.cost_basis, prices[0][0], DEEP).quantize(Decimal("1e-18"))
        assert row.lab_run_id == registry.G1_RUN
        assert row.abandon_gain == g1.ABANDON_UNLESS_GAIN
        assert row.size_multiplier == Decimal(1)

    # The glitch print neither sold anything nor became the peak.
    assert rows[mints["glitch0"]].peak_price == Decimal(1)
    # A dead pool's runner is worth nothing; the three quarters sold stand.
    scaledead = rows[mints["scaledead0"]]
    assert scaledead.exit_proceeds_usd == scaledead.realised_usd > 0
    assert "no tradeable pool" in scaledead.exit_evidence

    # ---- the ratchet ------------------------------------------------------------
    moves = list((await lab_session.execute(
        select(RafiqLabAdjustment).where(RafiqLabAdjustment.lab_run_id == registry.G1_RUN)
        .order_by(RafiqLabAdjustment.at, RafiqLabAdjustment.created_at)
    )).scalars())
    assert moves, "the floor never moved although wave 1 made money"
    assert all(m.parameter == "equity_ratchet_floor" for m in moves)
    assert all(m.new_value > m.old_value for m in moves), "the floor came down"
    assert moves[0].old_value == Decimal(950)
    state = (await lab_session.execute(
        select(RafiqLabRunState).where(RafiqLabRunState.lab_run_id == registry.G1_RUN)
    )).scalars().one()
    assert state.ratchet_floor == moves[-1].new_value.quantize(Decimal("0.0001"))
    # Both are stored at 4dp, each rounded from its own unrounded value.
    assert abs(state.ratchet_floor - state.ratchet_high_water * Decimal("0.97")) \
        <= Decimal("0.0001")

    # Wave 3 arrived after the dead pools sank marked equity under the floor.
    assert mints["late0"] not in rows and mints["late1"] not in rows, \
        "the ratchet did not stop new entries"
    positions = list(rows.values())
    cash = service.cash(book, positions)
    assert cash == book.starting_equity - sum(p.cost_basis for p in positions) + sum(
        p.exit_proceeds_usd for p in positions)
    assert cash <= state.ratchet_floor, (cash, state.ratchet_floor)
    halted = (await lab_session.execute(
        select(RafiqLabDailyState).where(RafiqLabDailyState.strategy_id == book.id)
    )).scalars().one()
    assert halted.halted and "ratchet floor" in halted.halted_reason
    # ...and it never force-closed: each dead pool left at its own box.
    for i in range(4):
        dead = rows[mints[f"dead{i}"]]
        assert dead.closed_at == dead.opened_at + g1.MAX_HOLD
        assert dead.exit_proceeds_usd == 0


@pytest.mark.integration
async def test_a_frozen_abandon_threshold_is_the_one_evaluated(
    lab_session, monkeypatch
) -> None:
    """`evaluate(abandon_gain=...)` is fed the threshold stored on the row, so a
    position opened under a loosened threshold is judged by it."""
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    service = RafiqLabService(lab_session)
    await service.activate(now=T0 - timedelta(minutes=1))
    book = await g1_book(lab_session)
    rows = path((0, 1), (2, "1.06"), length=20)
    ids = {}
    for tag, gain in (("strict", g1.ABANDON_UNLESS_GAIN), ("loose", Decimal("0.03"))):
        mint = await seed_path(lab_session, tag, T0 - timedelta(minutes=30), rows)
        pos = RafiqLabPosition(
            strategy_id=book.id, lab_run_id=book.lab_run_id, mint_address=mint, leg=1,
            opened_at=T0 - timedelta(minutes=10), entry_price=Decimal(1),
            entry_observed_price=Decimal(1), quantity=Decimal(10), cost_basis=Decimal(10),
            entry_liquidity_usd=DEEP, stop_price=Decimal("0.88"), stop_pct=Decimal(12),
            trailing_frac=g1.RUNNER_TRAIL, max_hold_seconds=2700, status="open",
            peak_price=Decimal(1), last_mark_price=Decimal(1),
            last_mark_liquidity_usd=DEEP, last_evaluated_at=T0,
            scaled_out=False, fraction_open=Decimal(1), realised_usd=Decimal(0),
            abandon_gain=gain, size_multiplier=Decimal(1))
        lab_session.add(pos)
        await lab_session.flush()
        ids[tag] = pos.id

    await service.tick(now=T0)

    got = {tag: (await lab_session.get(RafiqLabPosition, pid)) for tag, pid in ids.items()}
    assert got["strict"].status == "closed"
    assert got["strict"].exit_reason == g1.Exit.ABANDON
    assert got["loose"].status == "open", "the stored threshold was not the one used"


@pytest.mark.integration
async def test_the_bet_is_one_percent_of_the_current_book(lab_session, monkeypatch) -> None:
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    service = RafiqLabService(lab_session)
    await service.activate(now=T0 - timedelta(hours=1))
    book = await g1_book(lab_session)
    # +$100 realised earlier today: the book is $1,100, so the bet is $11.
    lab_session.add(RafiqLabPosition(
        strategy_id=book.id, lab_run_id=book.lab_run_id,
        mint_address="G1won".ljust(44, "8"), leg=1, opened_at=T0 - timedelta(minutes=50),
        entry_price=Decimal(1), entry_observed_price=Decimal(1), quantity=Decimal(10),
        cost_basis=Decimal(10), stop_price=Decimal("0.88"), stop_pct=Decimal(12),
        max_hold_seconds=2700, status="closed", peak_price=Decimal(11),
        last_evaluated_at=T0, closed_at=T0 - timedelta(minutes=5),
        exit_price=Decimal(11), exit_observed_price=Decimal(11),
        exit_proceeds_usd=Decimal(110), exit_reason=g1.Exit.RUNNER_TRAIL,
        scaled_out=False, fraction_open=Decimal(1), realised_usd=Decimal(0)))
    mint = await seed_path(lab_session, "sized", T0, path((0, 1), length=5))

    await service.tick(now=T0)

    row = await g1_row(lab_session, RafiqLabPosition, mint)
    assert row.cost_basis == g1.position_size(Decimal(1100)) == Decimal("11.00")


@pytest.mark.integration
async def test_the_floor_survives_a_restart(lab_session, monkeypatch) -> None:
    """A new service is a restarted worker. The floor it reads is the one the
    last one wrote, not `EquityRatchet`'s $950."""
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    first = RafiqLabService(lab_session)
    await first.activate(now=T0 - timedelta(hours=1))
    book = await g1_book(lab_session)
    ratchet = await first._ratchet(book, Decimal(1400), now=T0)
    assert ratchet.floor == Decimal("1358.00")
    await lab_session.flush()

    again = RafiqLabService(lab_session)
    reread = await again._ratchet(book, Decimal(1000), now=T0 + timedelta(minutes=1))
    assert reread.floor == Decimal("1358.00"), "the floor fell on a restart"
    halted, reason = reread.check(Decimal(1000))
    assert halted and reason.endswith("no new entries")


@pytest.mark.integration
async def test_archived_books_are_kept_drained_and_never_reopened(
    lab_session, monkeypatch
) -> None:
    """Prod's ledger at deploy: A2-F2 under `F2-and-earlier`, some of it open.

    The G1 run is new rows at $1,000. F2's row is not rewritten, the archived
    books open nothing, and what they still hold settles on its own rules."""
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    service = RafiqLabService(lab_session)
    now = datetime.now(UTC)
    archived = await service.activate(now=now - timedelta(days=2),
                                      run=registry.ARCHIVED_RUN)
    f2 = next(r for r in archived if r.code == "F2")
    before = (f2.id, f2.lane, f2.starting_equity, f2.profile_digest, f2.activated_at)

    mint = await seed_candidate(lab_session, now, tag="archopen")
    lab_session.add(RafiqLabPosition(
        strategy_id=f2.id, lab_run_id=f2.lab_run_id, mint_address=mint, leg=1,
        opened_at=now - timedelta(hours=9), entry_price=Decimal("0.001"),
        entry_observed_price=Decimal("0.001"), quantity=Decimal(10_000),
        cost_basis=Decimal(10), entry_liquidity_usd=Decimal(250_000),
        stop_price=Decimal("0.00088"), target_price=Decimal("0.0013"),
        stop_pct=Decimal(12), trailing_frac=Decimal("0.20"), max_hold_seconds=28800,
        status="open", peak_price=Decimal("0.001"), last_mark_price=Decimal("0.001"),
        last_evaluated_at=now - timedelta(minutes=1)))
    fresh = await seed_candidate(lab_session, now, tag="archfresh")
    await lab_session.flush()

    result = await service.tick(now=now)

    assert result["run"] == registry.G1_RUN
    assert sorted(result["strategies"]) == CURRENT_BOOKS
    g1_row = await g1_book(lab_session)
    assert g1_row.starting_equity == Decimal("1000.00")
    assert g1_row.activated_at == now
    await lab_session.refresh(f2)
    assert (f2.id, f2.lane, f2.starting_equity, f2.profile_digest,
            f2.activated_at) == before, "the F2 config row was rewritten"

    held = list((await lab_session.execute(
        select(RafiqLabPosition).where(RafiqLabPosition.strategy_id == f2.id)
    )).scalars())
    assert len(held) == 1, "an archived book opened a position"
    assert held[0].status == "closed" and held[0].exit_reason == "max_hold", \
        "the archived position was not settled on its own 8h box"
    assert result["archived_closed"] == 1
    # The admission is fresh but predates G1's activation instant: nothing
    # may trade it, which is the boundary a new run inherits.
    assert not list((await lab_session.execute(
        select(RafiqLabPosition).where(RafiqLabPosition.mint_address == fresh)
    )).scalars())
    # Every stored run is still queryable by id.
    runs = set((await lab_session.execute(select(RafiqLabStrategy.lab_run_id))).scalars())
    assert {registry.ARCHIVED_RUN, registry.G1_RUN} <= runs


@pytest.mark.integration
async def test_a_g1_cycle_leaves_the_existing_wallet_byte_identical(
    lab_session, monkeypatch
) -> None:
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    now = datetime.now(UTC)
    await seed_existing_wallet(lab_session, now)
    service = RafiqLabService(lab_session)
    await service.activate(now=now - timedelta(hours=1))
    await seed_candidate(lab_session, now, tag="g1cycle")
    before = await digest(lab_session)

    await service.tick(now=now)
    await service.tick(now=now + timedelta(minutes=1))

    assert await digest(lab_session) == before
    book = await g1_book(lab_session)
    opened = list((await lab_session.execute(
        select(RafiqLabPosition).where(RafiqLabPosition.strategy_id == book.id)
    )).scalars())
    assert len(opened) == 1 and opened[0].lab_run_id == registry.G1_RUN
    days = list((await lab_session.execute(
        select(RafiqLabDailyState).where(RafiqLabDailyState.strategy_id == book.id)
    )).scalars())
    assert days and {d.lab_run_id for d in days} == {registry.G1_RUN}


def test_the_current_run_trades_a2_to_e2_and_g1() -> None:
    """Each entering book files its own decisions, keyed by `strategy_id`.

    Pinned rather than computed: G1 replaced F2 and the brief archived A2-E2,
    then Karthik re-armed A2-E2 next to G1 the same day. Which books collect
    the sample is a visible edit, never a silent one."""
    current = registry.RUNS[registry.CURRENT_RUN]
    assert [s.code for s in current if s.enters] == CURRENT_BOOKS
    assert not any(s.enters for s in registry.RUNS[registry.ARCHIVED_RUN])
    # Last, so HQ's five desks pair with A2-E2 as they did before G1.
    assert registry.STRATEGIES[-1] is registry.G1


@pytest.mark.integration
async def test_a_book_that_joins_a_run_late_trades_nothing_from_before_it_joined(
    lab_session, monkeypatch
) -> None:
    """Prod, 2026-09-17: A2-E2 joined G1's run after G1 had started. The run's
    candidate window opens at its EARLIEST activation, so a fresh admission
    from before A2-E2 existed reached them too; only each book's own
    `activated_at` keeps it out."""
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    service = RafiqLabService(lab_session)
    now = datetime.now(UTC)
    monkeypatch.setitem(registry.RUNS, registry.G1_RUN, (registry.G1,))
    await service.activate(now=now - timedelta(hours=1))
    monkeypatch.setitem(registry.RUNS, registry.G1_RUN,
                        (*registry.REARMED, registry.G1))
    await service.activate(now=now - timedelta(minutes=10))

    before = await seed_candidate(lab_session, now, tag="joinbefore")
    await lab_session.execute(
        update(RadarToken).where(RadarToken.mint_address == before)
        .values(first_detected_at=now - timedelta(minutes=12)))
    after = await seed_candidate(lab_session, now, tag="joinafter")
    await service.tick(now=now)

    async def books(mint):
        return set((await lab_session.execute(
            select(RafiqLabStrategy.code)
            .join(RafiqCandidate, RafiqCandidate.strategy_id == RafiqLabStrategy.id)
            .where(RafiqCandidate.mint_address == mint)
        )).scalars())

    assert await books(before) == {"G1"}, "a late book traded from before it joined"
    assert await books(after) == set(CURRENT_BOOKS), "a late book saw nothing at all"


def test_the_canonical_config_and_the_code_agree() -> None:
    """`strategy_G1.json` is canonical. Wherever `strategy_G1.py` or
    `learning.py` carries the same number, it must be the same number."""
    cfg, exits = registry.G1_CONFIG, registry.G1_CONFIG["exits"]
    assert cfg["book"] == "G1" and cfg["replaces"] == "F2"
    assert "learning" in cfg, "the canonical config is the one with a learning block"
    assert D(cfg["entry_gate"]["min_liquidity_usd"]) == g1.MIN_LIQUIDITY_USD
    assert D(cfg["entry_gate"]["min_market_cap_usd"]) == g1.MIN_MARKET_CAP_USD
    assert timedelta(minutes=exits["abandon_if_flat"]["at_minutes"]) == g1.ABANDON_AFTER
    assert D(exits["abandon_if_flat"]["min_gain_pct"]) / 100 == g1.ABANDON_UNLESS_GAIN
    assert D(exits["scale_out"]["at_multiple"]) == g1.SCALE_OUT_AT
    assert D(exits["scale_out"]["sell_fraction"]) == g1.SCALE_OUT_FRACTION
    assert D(exits["runner"]["trail_frac"]) == g1.RUNNER_TRAIL
    assert exits["runner"]["take_profit"] is None
    assert D(exits["stop"]) == g1.STOP_MULT
    assert timedelta(minutes=exits["max_hold_minutes"]) == g1.MAX_HOLD
    ratchet = cfg["equity_ratchet"]
    assert D(ratchet["give_back_pct"]) / 100 == g1.RATCHET_GIVE_BACK
    assert D(ratchet["initial_floor_usd"]) == g1.EquityRatchet().floor
    assert D(cfg["starting_capital_usd"]) == g1.EquityRatchet().high_water \
        == config.STARTING_EQUITY
    assert ratchet["force_close_open_positions"] is False
    assert g1.position_size(Decimal(1000)) == D(cfg["sizing"]["position_usd"])
    # G1 is gated by the lab's daily breaker, whose policy is E's.
    assert registry.G1.daily_breaker
    assert D(cfg["daily_breaker"]["max_daily_drawdown_pct"]) / 100 == \
        DAILY_POLICY.max_daily_drawdown
    lrn = cfg["learning"]
    lo, hi = lrn["abandon_calibration"]["bounded"]
    assert (D(lo) / 100, D(hi) / 100) == (learning.ABANDON_GAIN_MIN,
                                          learning.ABANDON_GAIN_MAX)
    assert D(lrn["abandon_calibration"]["step"]) / 100 == learning.ABANDON_STEP
    assert D(lrn["abandon_calibration"]["starts_at"]) / 100 == g1.ABANDON_UNLESS_GAIN
    assert lrn["regime_monitor"]["window"] == learning.REGIME_WINDOW
    assert lrn["safety"]["min_sample_before_any_change"] == learning.MIN_SAMPLE


def test_g1_digest_is_the_config_not_its_prose() -> None:
    """Editing a `_why` must not halt the book on drift; editing a rule must."""
    base = registry.G1.digest
    registry.G1_CONFIG["_THESIS"]["in_one_line"] += " (edited)"
    try:
        assert registry.G1.digest == base
    finally:
        registry.G1_CONFIG["_THESIS"]["in_one_line"] = \
            registry.G1_CONFIG["_THESIS"]["in_one_line"].removesuffix(" (edited)")
    registry.G1_CONFIG["exits"]["stop"] = 0.9
    try:
        assert registry.G1.digest != base
    finally:
        registry.G1_CONFIG["exits"]["stop"] = 0.88
    assert registry.G1.digest == base
