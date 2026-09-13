"""Invariants that must hold no matter what path the price takes.

The seven verification tests check known scenarios. These check the ones nobody
thought to write down: driven over thousands of minutes of adversarial price
action — every re-centre, every margin rejection, every stop-out — the books
still have to balance.

The paths are deterministic (a seeded PRNG, not a fixture chosen to be kind),
so a failure here is reproducible and is a real defect rather than a flake.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from app.labs.forex_lab.engine import GridConfig, GridEngine

PIP = 0.0001
C0 = 1.10000
START = datetime(2022, 3, 1, 0, 0, tzinfo=UTC)


def random_walk(n: int, seed: int, drift: float = 0.0,
                vol_pips: float = 3.0) -> list[tuple]:
    """One candle a minute. Wicks on both sides, so most candles are genuinely
    ambiguous between the two orderings and the clone-and-compare path is the
    one under test."""
    rng = random.Random(seed)
    out, price = [], C0
    t = START
    for _ in range(n):
        move = (rng.gauss(drift, vol_pips)) * PIP
        close = round(price + move, 7)
        wick = abs(rng.gauss(0, vol_pips)) * PIP
        high = round(max(price, close) + wick, 7)
        low = round(min(price, close) - wick, 7)
        out.append((t, price, high, low, close))
        price = close
        t += timedelta(minutes=1)
    return out


def check(e: GridEngine, mid: float) -> None:
    cfg = e.cfg

    # Equity is balance plus the mark, by construction and after every event.
    assert e.equity(mid) == pytest.approx(e.balance + e.unrealized(mid), abs=1e-9)

    # Used margin is the sum of what each position holds, never a running
    # total that drifted.
    assert e.used_margin == pytest.approx(
        sum(p.margin for p in e.positions), abs=1e-9)

    # A position's opening order is NOT also resting: it was consumed, and it
    # comes back only when the take-profit closes the position.
    resting = [(o.level, o.kind) for o in e.orders]
    assert len(resting) == len(set(resting)), f"duplicate resting order: {resting}"
    for p in e.positions:
        assert (p.origin.level, p.origin.kind) not in resting, (
            f"{p.origin.kind} at level {p.origin.level} is open AND resting")

    # Every resting order sits on its own grid, at a whole number of steps from
    # the centre, and inside the re-centre boundary.
    for o in e.orders:
        k = (o.price - e.center) / cfg.step
        assert abs(k - round(k)) < 1e-6, f"{o.price} is not on the grid at {e.center}"
        assert 1 <= abs(round(k)) <= cfg.levels


def test_the_books_balance_over_every_kind_of_path():
    """The global one: every dollar that moved the balance is in the trade
    list, and every dollar in the trade list moved the balance."""
    for seed, drift, vol in ((1, 0.0, 3.0), (2, 0.4, 2.0), (3, -0.4, 2.0),
                             (4, 0.0, 9.0), (5, 0.05, 1.0)):
        candles = random_walk(4000, seed, drift, vol)
        e = GridEngine(GridConfig(step_pips=25, levels=4), C0, candles[0][0])
        for minute, o, h, l, c in candles:
            e.step(minute, o, h, l, c)
        last = candles[-1]
        e.finish(last[0], last[4])

        assert e.positions == [], "finish() must leave the account in cash"
        realised = sum(t.pnl for t in e.trades)
        swap = sum(t.swap for t in e.trades)
        assert e.balance == pytest.approx(
            e.cfg.start_equity + realised + swap, abs=1e-6), (
            f"seed {seed}: balance does not equal the trade list")
        for t in e.trades:
            assert t.pnl == pytest.approx(t.gross - t.cost, abs=1e-9)


def test_the_state_is_consistent_after_every_single_candle():
    for seed, drift, vol in ((11, 0.0, 4.0), (12, 0.6, 3.0), (13, -0.6, 3.0)):
        candles = random_walk(2000, seed, drift, vol)
        e = GridEngine(GridConfig(step_pips=25, levels=4), C0, candles[0][0])
        for minute, o, h, l, c in candles:
            e.step(minute, o, h, l, c)
            check(e, c)


def test_a_trending_market_re_centres_and_survives_it():
    """The path a grid is supposed to hate: one direction, no mean reversion.
    It must lose money, and it must lose it through re-centres rather than by
    the simulation falling over."""
    candles = random_walk(6000, 21, drift=1.2, vol_pips=2.0)
    e = GridEngine(GridConfig(step_pips=25, levels=4), C0, candles[0][0])
    for minute, o, h, l, c in candles:
        e.step(minute, o, h, l, c)
    e.finish(candles[-1][0], candles[-1][4])

    assert e.stats["recenters"] > 0
    assert e.balance < e.cfg.start_equity
    assert e.stats["recenter_loss"] < 0


def test_a_rejected_fill_never_consumes_the_margin_it_was_refused():
    """The one that actually bit, in iteration 1. If a rejection charged
    margin, a tight account would ratchet itself shut."""
    candles = random_walk(3000, 31, drift=0.0, vol_pips=5.0)
    e = GridEngine(GridConfig(step_pips=15, levels=6, start_equity=300.0),
                   C0, candles[0][0])
    for minute, o, h, l, c in candles:
        e.step(minute, o, h, l, c)
        assert e.used_margin == pytest.approx(
            sum(p.margin for p in e.positions), abs=1e-9)
    assert e.stats["rejected_fills"] > 0, "the fixture must actually hit the cap"


def test_the_neutral_grid_holds_no_short_below_the_centre():
    """With the stop orders removed, the only things that fill below the centre
    are buy limits and the only things above are sell limits. A short opened
    below the centre would mean a stop order survived `stop_multiplier = 0`."""
    candles = random_walk(3000, 41, drift=0.0, vol_pips=4.0)
    e = GridEngine(GridConfig(step_pips=25, levels=4, stop_multiplier=0.0),
                   C0, candles[0][0])
    for minute, o, h, l, c in candles:
        e.step(minute, o, h, l, c)
        for p in e.positions:
            if p.origin.level < 0:
                assert p.side == 1, "a short below the centre in a neutral grid"
            else:
                assert p.side == -1
    assert not any(o.kind.endswith("_stop") for o in e.orders)
    assert e.stats["fills"] > 0


def test_two_runs_over_an_adversarial_path_are_byte_identical():
    """Determinism, on a path that exercises re-centres and rejections rather
    than on the tidy one in test_engine.py."""
    candles = random_walk(5000, 51, drift=0.3, vol_pips=6.0)

    def run() -> tuple:
        e = GridEngine(GridConfig(step_pips=15, levels=6, start_equity=500.0),
                       C0, candles[0][0])
        for minute, o, h, l, c in candles:
            e.step(minute, o, h, l, c)
        e.finish(candles[-1][0], candles[-1][4])
        return ([(t.opened_at, t.closed_at, t.side, t.lots, t.entry, t.exit,
                  t.kind, t.reason, t.gross, t.cost, t.swap, t.pnl)
                 for t in e.trades], e.balance, e.stats, e.min_equity)

    a, b = run(), run()
    assert a == b
    assert a[0], "the fixture must actually trade"
