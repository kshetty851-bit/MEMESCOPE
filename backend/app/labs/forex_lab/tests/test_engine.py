"""The seven verification tests the brief names, plus the invariants that make
their expected values trustworthy.

Every expected number below is a hand calculation, written out in the test that
asserts it. With C = 1.10000, S = 25 pips, spread 0.8 pip and stop slippage
0.2 pip, the arithmetic is small enough to do on paper:

    half spread   0.00004     slippage   0.00002
    1 micro lot   €1,000      1 pip on it   $0.10
    a 25-pip take-profit on a LIMIT fill   $2.50 gross - $0.08 spread = $2.42
    the same on a STOP fill                $2.50 - $0.08 - $0.02      = $2.40
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.labs.forex_lab.engine import GridConfig, GridEngine
from app.labs.forex_lab.tests.helpers import PIP, cents, run, walk

C0 = 1.10000
T0 = datetime(2023, 1, 3, 10, 0, tzinfo=UTC)  # a Tuesday, 05:00 New York


def make(**kw) -> GridEngine:
    cfg = GridConfig(step_pips=25, levels=4, lots=1.0, **kw)
    return GridEngine(cfg, C0, T0)


# --- 1. limit vs stop fill semantics -----------------------------------------


def test_limit_and_stop_fill_semantics_and_pnl_to_the_cent():
    """Down 60 pips, then back to the centre. S=25, N=4.

    On the way down price reaches 1.09750 and 1.09500 (1.09250 is below the
    1.09400 turn). At each, the BUY LIMIT and the SELL STOP both fill — that is
    what makes the grid hedged.

        1.09750  buy limit  -> long  @ 1.09754  tp 1.10000
                 sell stop  -> short @ 1.09744  tp 1.09500
        1.09500  buy limit  -> long  @ 1.09504  tp 1.09750
                 sell stop  -> short @ 1.09494  tp 1.09250
                 and the 1.09750 short's take-profit is 1.09500, so it closes
                 here: buys at 1.09504, +$2.40 (a stop fill: spread AND slip)

    On the way back up, two limit-fill take-profits — and one more entry:

        1.09750  the 1.09500 long closes at 1.09746   +$2.42
        1.09750  the sell stop re-placed here when the FIRST short took profit
                 fires again. The candle from 1.09750 to 1.09800 has, as its
                 worse ordering, 1.09750 -> 1.09800 -> 1.09750 -> 1.09800, and
                 the middle leg is price FALLING through 1.09750, which is
                 precisely what a sell stop at 1.09750 is an order to do. A
                 short opens at 1.09744 into a rising market.
        1.10000  the 1.09750 long closes at 1.09996   +$2.42

    Five fills, three closes, $7.24 realised, and two shorts left open: the one
    from 1.09500, whose take-profit at 1.09250 was never reached, and the
    re-armed one from 1.09750, whose take-profit at 1.09500 the path never
    revisits. See DECISIONS.md correction A — the count of four was my
    arithmetic, not the engine's.
    """
    e = make()
    run(e, walk(C0, 1.09400, t0=T0))
    run(e, walk(1.09400, C0, t0=T0 + timedelta(minutes=20)))

    assert e.stats["fills"] == 5
    assert e.stats["rejected_fills"] == 0
    assert e.stats["recenters"] == 0
    assert len(e.trades) == 3

    order_of_events = [(t.kind, t.reason, cents(t.pnl)) for t in e.trades]
    assert order_of_events == [
        ("sell_stop", "tp", 2.40),
        ("buy_limit", "tp", 2.42),
        ("buy_limit", "tp", 2.42),
    ]

    assert cents(e.trades[0].entry) == cents(1.09744)
    assert cents(e.trades[0].exit) == cents(1.09504)
    assert cents(e.balance) == 1007.24

    # Two survivors, both short, both from sell stops, neither near its target.
    assert len(e.positions) == 2
    assert {(p.side, round(p.entry, 5), round(p.tp, 5)) for p in e.positions} == {
        (-1, 1.09494, 1.09250),  # opened on the way down at 1.09500
        (-1, 1.09744, 1.09500),  # the re-armed stop, opened on the way back up
    }


def test_pnl_is_exactly_gross_minus_cost():
    """The invariant that makes the cost breakdown in the report add up."""
    e = make()
    run(e, walk(C0, 1.09400, t0=T0))
    run(e, walk(1.09400, C0, t0=T0 + timedelta(minutes=20)))
    assert e.trades
    for t in e.trades:
        assert t.pnl == pytest.approx(t.gross - t.cost, abs=1e-9)


# --- 2. hedging ---------------------------------------------------------------


def test_long_and_short_coexist_and_close_independently():
    """One level, two positions, opposite sides, never netted."""
    e = make()
    run(e, walk(C0, 1.09700, t0=T0))

    assert len(e.positions) == 2
    long_, short = sorted(e.positions, key=lambda p: -p.side)
    assert long_.side == 1 and short.side == -1
    assert round(long_.entry, 5) == 1.09754
    assert round(short.entry, 5) == 1.09744

    # Down to 1.09500 closes the short at its take-profit and leaves the long
    # exactly as it was — same object, same entry, same size.
    before = (short.side, short.lots, short.entry)
    run(e, walk(1.09700, 1.09500, t0=T0 + timedelta(minutes=30)))

    assert long_ in e.positions
    assert (long_.side, long_.lots, long_.entry) == (1, 1.0, pytest.approx(1.09754))
    assert short not in e.positions
    closed = [t for t in e.trades if t.kind == "sell_stop"]
    assert len(closed) == 1
    assert (closed[0].side, closed[0].lots) == (before[0], before[1])


# --- 3. take-profit re-placement ---------------------------------------------


def test_take_profit_replaces_its_own_grid_order():
    e = make()
    run(e, walk(C0, 1.09700, t0=T0))

    def level_orders():
        return {(o.level, o.kind) for o in e.orders}

    # The two orders at 1.09750 have been consumed by their fills.
    assert (-1, "buy_limit") not in level_orders()
    assert (-1, "sell_stop") not in level_orders()

    run(e, walk(1.09700, 1.09500, t0=T0 + timedelta(minutes=30)))
    # The short's take-profit fired at 1.09500, so its sell stop is back —
    # at the same level, the same price, the same size.
    assert (-1, "sell_stop") in level_orders()
    replaced = next(o for o in e.orders if (o.level, o.kind) == (-1, "sell_stop"))
    assert round(replaced.price, 5) == 1.09750
    assert replaced.lots == 1.0
    assert round(replaced.tp, 5) == 1.09500
    # The long's take-profit is 1.10000 and has not fired, so its buy limit
    # is still gone.
    assert (-1, "buy_limit") not in level_orders()


# --- 4. re-centre -------------------------------------------------------------


def test_recenter_closes_everything_and_realises_the_open_pnl():
    """Up 100 pips from 1.10000 reaches C + N*S = 1.11000 exactly.

    Level 4's orders fill there and the re-centre closes them at the same
    price — two spreads for nothing, which is the conservative ordering.

    Open at the moment of the re-centre, after three buy-stop take-profits
    have already banked $2.40 each:

        short 1.10246   short 1.10496   short 1.10746   short 1.10996
        long  1.11006

    Everything closes at market, which pays spread AND slippage: shorts buy at
    1.11006, the long sells at 1.10994.

        -7.60  -5.10  -2.60  -0.10   (shorts)      -0.12  (long)   = -15.52

    which is the open P&L marked at the mid (-15.22) minus five exits at
    $0.06 each (-0.30).
    """
    e = make()
    run(e, walk(C0, 1.11000, t0=T0))

    assert e.stats["recenters"] == 1
    assert e.stats["rejected_fills"] == 0
    assert cents(e.stats["recenter_loss"]) == -15.52

    closed_by_recenter = [t for t in e.trades if t.reason == "recenter"]
    assert len(closed_by_recenter) == 5
    open_pnl_at_mid = sum(t.gross for t in closed_by_recenter)
    exit_costs = 5 * 1.0 * (0.00004 + 0.00002) * 1000
    entry_costs = sum(t.cost for t in closed_by_recenter) - exit_costs
    assert cents(open_pnl_at_mid - exit_costs - entry_costs) == -15.52
    assert cents(exit_costs) == 0.30

    # Three buy-stop take-profits at $2.40 on the way up.
    assert cents(e.balance) == cents(1000 + 3 * 2.40 - 15.52)

    # Everything closed, everything cancelled, the grid rebuilt around here.
    assert e.positions == []
    assert round(e.center, 5) == 1.11000
    assert len(e.orders) == 4 * e.cfg.levels  # 2 per level, both sides
    assert min(o.price for o in e.orders) == pytest.approx(1.11000 - 4 * 25 * PIP)
    assert max(o.price for o in e.orders) == pytest.approx(1.11000 + 4 * 25 * PIP)


# --- 5. margin and stop-out, at the boundary ---------------------------------


def test_margin_rejection_at_the_exact_boundary():
    """A fill is rejected when it would take used margin ABOVE 90% of equity,
    so exactly 90% is still accepted.

    One buy limit, alone, so the boundary is one number. It fills at 1.09750 +
    0.00004 = 1.09754 and needs 1,000 x 1.09754 / 10 = $109.754 of margin, so
    with no position open the boundary equity is 109.754 / 0.9 = $121.9489.
    """
    margin = 1000 * 1.09754 / 10
    boundary = margin / 0.90
    assert round(boundary, 4) == 121.9489

    def one_buy_limit(equity):
        e = make(start_equity=equity)
        e.orders = [o for o in e.orders if (o.level, o.kind) == (-1, "buy_limit")]
        run(e, walk(C0, 1.09740, t0=T0))
        return e

    at = one_buy_limit(boundary)
    assert at.stats["rejected_fills"] == 0, "exactly 90% is not above 90%"
    assert len(at.positions) == 1
    assert round(at.positions[0].entry, 5) == 1.09754
    assert at.used_margin == pytest.approx(0.90 * boundary, abs=1e-9)

    below = one_buy_limit(boundary - 0.01)
    assert below.positions == [], "a cent under the boundary rejects it"
    assert below.stats["rejected_fills"] == 1


def test_the_cheaper_of_two_orders_at_one_level_can_still_fit():
    """The buy limit and the sell stop at a level do not cost the same margin,
    because they do not fill at the same price: 1.09754 against 1.09744, ten
    cents of notional apart. One cent below the LONG's boundary the long is
    rejected — which leaves used margin at zero — and the short then fits.

        cap = 0.9 x 121.9389 = 109.74501
        long  109.754 > cap  -> rejected
        short 109.744 < cap  -> accepted

    See DECISIONS.md correction C. Asserted because it is the behaviour a
    rejection has to have: rejecting a fill must not consume the margin it was
    refused.
    """
    boundary = (1000 * 1.09754 / 10) / 0.90
    e = make(start_equity=boundary - 0.01)
    run(e, walk(C0, 1.09740, t0=T0))

    assert e.stats["rejected_fills"] == 1
    assert len(e.positions) == 1
    assert e.positions[0].side == -1
    assert round(e.positions[0].entry, 5) == 1.09744


def test_stop_out_at_the_exact_boundary():
    """Everything closes when equity falls BELOW 50% of used margin, so exactly
    50% survives.

    One long micro lot at 1.09754 carries $109.754 of margin, so the stop-out
    line is $54.877 of equity. Equity is the balance plus the long marked at
    the bid, so with balance B and mid m:

        B + (m - 0.00004 - 1.09754) * 1000 = 54.877

    Starting from B = 200 the line sits at m = 1.24215 — far above, which is
    why this test walks the price up rather than down: a long that is deep in
    profit cannot be stopped out, so the boundary is tested by moving the line
    instead, with a balance small enough to reach it.
    """
    e = make(start_equity=200.0)
    e.orders = [o for o in e.orders if o.kind == "buy_limit" and o.level == -1]
    run(e, walk(C0, 1.09740, t0=T0))
    assert len(e.positions) == 1
    pos = e.positions[0]
    margin = pos.margin
    assert round(margin, 3) == round(1000 * 1.09754 / 10, 3)

    # Solve for the mid at which equity is exactly half the margin.
    line = 0.5 * margin
    mid_at_line = (line - e.balance) / 1000.0 + 0.00004 + pos.entry
    assert e.equity(mid_at_line) == pytest.approx(line, abs=1e-6)

    e._check_stop_out(mid_at_line, T0)
    assert e.stats["stopouts"] == 0, "exactly 50% is not below 50%"
    assert len(e.positions) == 1

    e._check_stop_out(mid_at_line - 0.00001, T0)
    assert e.stats["stopouts"] == 1
    assert e.positions == []


# --- 6. swap ------------------------------------------------------------------


def test_two_rollovers_accrue_exactly_twice_the_rate():
    """Monday 2023-01-09 and Tuesday 2023-01-10 — two weekday rollovers at
    17:00 New York, neither of them the Wednesday that carries the weekend.

    The 2023 long rate is -$0.0655 per micro lot per night, so one micro lot
    held across both owes exactly -$0.1310.
    """
    from app.labs.forex_lab import config

    long_rate, _ = config.SWAP_USD_PER_MICRO_LOT[2023]
    mon = datetime(2023, 1, 9, 10, 0, tzinfo=UTC)  # 05:00 New York

    e = GridConfig(step_pips=25, levels=4, lots=1.0)
    eng = GridEngine(e, C0, mon)
    run(eng, walk(C0, 1.09740, t0=mon))
    assert len(eng.positions) == 2
    pos = next(p for p in eng.positions if p.side > 0)

    flat = (1.09740, 1.09740, 1.09740, 1.09740)
    eng.step(datetime(2023, 1, 9, 23, 0, tzinfo=UTC), *flat)  # 18:00 NY Mon
    assert pos.swap_paid == pytest.approx(long_rate, abs=1e-9)

    eng.step(datetime(2023, 1, 10, 23, 0, tzinfo=UTC), *flat)  # 18:00 NY Tue
    assert pos.swap_paid == pytest.approx(2 * long_rate, abs=1e-9)
    assert round(pos.swap_paid, 4) == -0.1310

    # And it reached the balance, once, not twice.
    assert eng.stats["swap_paid"] == pytest.approx(
        2 * (long_rate + config.SWAP_USD_PER_MICRO_LOT[2023][1]), abs=1e-9
    )


def test_wednesday_rollover_is_charged_three_times():
    """Wednesday 2023-01-11 settles on Monday, so it books three nights. Without
    it the weekend is simply never charged."""
    from app.labs.forex_lab import config

    long_rate, _ = config.SWAP_USD_PER_MICRO_LOT[2023]
    # Wednesday MORNING: Tuesday's rollover is already behind us, so Wednesday's
    # is the only one this fixture crosses. See DECISIONS.md correction D.
    wed = datetime(2023, 1, 11, 10, 0, tzinfo=UTC)  # 05:00 New York
    eng = GridEngine(GridConfig(step_pips=25, levels=4, lots=1.0), C0, wed)
    run(eng, walk(C0, 1.09740, t0=wed))
    pos = next(p for p in eng.positions if p.side > 0)

    flat = (1.09740, 1.09740, 1.09740, 1.09740)
    eng.step(datetime(2023, 1, 11, 23, 0, tzinfo=UTC), *flat)  # 18:00 NY Wed
    assert pos.swap_paid == pytest.approx(3 * long_rate, abs=1e-9)


def test_a_missing_friday_candle_still_charges_friday():
    """The Friday rollover lands on the weekly close, where the feed may have no
    tick. It is charged from the calendar, not from a candle's arrival."""
    from app.labs.forex_lab import config

    long_rate, _ = config.SWAP_USD_PER_MICRO_LOT[2023]
    thu = datetime(2023, 1, 12, 10, 0, tzinfo=UTC)
    eng = GridEngine(GridConfig(step_pips=25, levels=4, lots=1.0), C0, thu)
    run(eng, walk(C0, 1.09740, t0=thu))
    pos = next(p for p in eng.positions if p.side > 0)

    flat = (1.09740, 1.09740, 1.09740, 1.09740)
    # Thursday's rollover, then nothing until Monday morning: Friday's rollover
    # passed with the market shut and is still owed.
    eng.step(datetime(2023, 1, 12, 23, 0, tzinfo=UTC), *flat)  # 18:00 NY Thu
    assert pos.swap_paid == pytest.approx(long_rate, abs=1e-9)
    eng.step(datetime(2023, 1, 16, 10, 0, tzinfo=UTC), *flat)  # 05:00 NY Mon
    assert pos.swap_paid == pytest.approx(2 * long_rate, abs=1e-9)


# --- 7. determinism -----------------------------------------------------------


def _zigzag(n: int = 600) -> list[tuple]:
    """A fixed, reproducible path with no randomness in it: a 90-pip triangle
    wave that re-centres several times in both directions."""
    t = datetime(2023, 2, 1, 0, 0, tzinfo=UTC)
    out, price, direction = [], C0, -1
    for i in range(n):
        if i % 37 == 0:
            direction = -direction
        nxt = round(price + direction * 5 * PIP, 7)
        out.append((t, price, round(max(price, nxt), 7), round(min(price, nxt), 7), nxt))
        price = nxt
        t += timedelta(minutes=1)
    return out


def test_same_candles_and_config_give_an_identical_trade_list():
    candles = _zigzag()
    a, b = make(), make()
    run(a, candles)
    run(b, candles)

    def fingerprint(e):
        return [
            (
                t.opened_at,
                t.closed_at,
                t.side,
                t.lots,
                t.entry,
                t.exit,
                t.kind,
                t.reason,
                t.gross,
                t.cost,
                t.swap,
                t.pnl,
            )
            for t in e.trades
        ]

    assert a.trades, "the fixture must actually trade"
    assert fingerprint(a) == fingerprint(b)
    assert a.balance == b.balance
    assert a.stats == b.stats
    assert a.center == b.center


# --- the assumption the hand calculations rest on -----------------------------


def test_both_intracandle_orderings_agree_on_the_hand_computed_paths():
    """The expected values above are one calculation, not two, which is only
    legitimate if the 5-pip candles cannot separate the orderings. Forcing each
    ordering on its own must reproduce the same book."""
    for target in (1.09400, 1.11000):
        candles = walk(C0, target, t0=T0)
        low_first, high_first = make(), make()
        for minute, o, h, lo, c in candles:
            low_first._apply_swap(minute)
            low_first._walk(o, lo, h, c, minute)
            low_first.mark = c
            high_first._apply_swap(minute)
            high_first._walk(o, h, lo, c, minute)
            high_first.mark = c
        assert low_first.balance == pytest.approx(high_first.balance, abs=1e-9)
        assert len(low_first.trades) == len(high_first.trades)
        assert low_first.stats["fills"] == high_first.stats["fills"]


def test_the_worse_ordering_is_the_one_that_is_kept():
    """A candle wide enough to separate the orderings must resolve to the worse
    of the two, not the first or the nicer."""
    e = make()
    # Asymmetric on purpose: a candle whose high and low are the same distance
    # out and that closes where it opened is symmetric enough that both
    # orderings land on the same balance. +80 / -40 / close +60 does not.
    wide = (T0, C0, round(C0 + 80 * PIP, 7), round(C0 - 40 * PIP, 7), round(C0 + 60 * PIP, 7))

    low_first = e._clone()
    low_first._walk(wide[1], wide[3], wide[2], wide[4], wide[0])
    high_first = e._clone()
    high_first._walk(wide[1], wide[2], wide[3], wide[4], wide[0])
    assert low_first.balance != high_first.balance, "the fixture must separate them"

    e.step(*wide)
    assert e.equity(wide[4]) == pytest.approx(
        min(low_first.equity(wide[4]), high_first.equity(wide[4])), abs=1e-9
    )


# --- the margin call on a candle that trades nothing --------------------------


def test_the_margin_call_is_checked_on_a_candle_that_fires_nothing():
    """A grid can be walked into a stop-out by the MARK alone — price drifting
    against an open book without reaching a single order. Checking the stop-out
    only on candles that traded would miss most of them.

    A wide grid (500-pip steps) and a book with no pending orders left, so the
    candle provably reaches nothing: the only triggers are the position's own
    take-profit at 1.10000 and the re-centre boundary at 0.90000.

        long 1 micro lot at 1.05004, margin 1,000 x 1.05004 / 10 = $105.004
        stop-out line = 50% of that = $52.502
        equity at mid m = 200 + (m - 0.00004 - 1.05004) x 1000

    which crosses the line at m = 0.90258. 0.90300 is above it and survives;
    0.90100 is below it and does not — and both sit inside 0.90000..1.10000,
    so neither can fire anything.
    """
    from app.labs.forex_lab.engine import Order, Position

    def book(mid_at_start: float) -> GridEngine:
        e = GridEngine(
            GridConfig(step_pips=500, levels=4, lots=1.0, start_equity=200.0), C0, T0
        )
        e.orders = []
        origin = Order(-1, "buy_limit", 1.05000, +1, 1.0, 1.10000, -1)
        e.positions = [
            Position(
                side=+1,
                lots=1.0,
                entry=1.05004,
                tp=1.10000,
                margin=1000 * 1.05004 / 10,
                opened_at=T0,
                origin=origin,
                cost_paid=0.04,
            )
        ]
        e.mark = mid_at_start
        e._refresh_bounds()
        assert round(e._bound_down, 5) == 0.90000
        assert round(e._bound_up, 5) == 1.10000
        return e

    survives = book(0.90300)
    survives.step(T0 + timedelta(minutes=1), 0.90300, 0.90300, 0.90300, 0.90300)
    assert survives.stats["stopouts"] == 0
    assert len(survives.positions) == 1

    dies = book(0.90100)
    dies.step(T0 + timedelta(minutes=1), 0.90100, 0.90100, 0.90100, 0.90100)
    assert dies.stats["stopouts"] == 1
    assert dies.positions == []
    assert dies.stats["fills"] == 0, "nothing was reached; only the mark moved"


def test_min_equity_records_the_worst_the_account_ever_showed():
    """A run whose FINAL equity looks survivable can still have passed through
    zero on the way, and every ratio computed over it would be a number about
    an account that had stopped existing."""
    e = make()
    assert e.min_equity == 1000.0
    run(e, walk(C0, 1.09400, t0=T0))
    assert e.min_equity < 1000.0
    assert e.min_equity <= e.equity(1.09400)


# --- gaps ---------------------------------------------------------------------


def _gapped(distance_pips: float) -> GridEngine:
    """Friday's close, then Sunday's open `distance_pips` away. Nothing traded
    in between."""
    e = make()
    e.step(datetime(2023, 1, 6, 21, 59, tzinfo=UTC), C0, C0, C0, C0)
    assert e.positions == [], "the first candle is the centre; nothing fires"
    gap = round(C0 - distance_pips * PIP, 7)
    e.step(datetime(2023, 1, 8, 22, 0, tzinfo=UTC), gap, gap, gap, gap)
    return e


def test_an_order_the_market_gapped_over_is_still_reached():
    """A model that only looks inside a candle skips a weekend every week. The
    orders at 1.09750 and 1.09500 were both crossed by the gap and both fill;
    1.09250 is below the open and is still resting."""
    e = _gapped(60)
    assert e.stats["fills"] == 4
    assert (-3, "buy_limit") in {(o.level, o.kind) for o in e.orders}


def test_a_gap_lands_in_exactly_the_same_book_as_the_same_move_walked():
    """The documented convention, stated as the equivalence it actually is: a
    gapped order fills at its own level, so a 60-pip gap and a 60-pip walk end
    identically. The alternative — filling at the price the market reopened at
    — would hand a buy limit 35 pips of free entry every weekend, which is a
    windfall, not a cost. See the "Gaps" note at the top of engine.py.
    """
    gapped = _gapped(60)
    walked = make()
    run(walked, walk(C0, round(C0 - 60 * PIP, 7), t0=T0))

    def book(e):
        return {(p.origin.level, p.origin.kind): round(p.entry, 5) for p in e.positions}

    assert (
        book(gapped)
        == book(walked)
        == {
            (-1, "buy_limit"): 1.09754,  # level + half spread
            (-2, "buy_limit"): 1.09504,
            (-2, "sell_stop"): 1.09494,  # level - half spread - slip
        }
    )
    # The level-1 sell stop opened at 1.09744 and took profit at 1.09500 on the
    # way through, both times, for the same $2.40 — and its order is back.
    assert [round(t.pnl, 2) for t in gapped.trades] == [2.40]
    assert [round(t.pnl, 2) for t in walked.trades] == [2.40]
    assert gapped.balance == pytest.approx(walked.balance, abs=1e-9)
    assert (-1, "sell_stop") in {(o.level, o.kind) for o in gapped.orders}


def test_the_gap_leg_does_not_change_an_ordinary_contiguous_candle():
    """The rule must not touch the 2.4 million minutes where one candle's close
    IS the next one's open."""
    e = make()
    run(e, walk(C0, 1.09700, t0=T0))
    stop = next(p for p in e.positions if p.origin.kind == "sell_stop")
    assert round(stop.entry, 5) == 1.09744
