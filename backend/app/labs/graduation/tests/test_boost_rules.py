"""Boost Lab's 18 Oct rules: the entry ratio and the three-loss pause.

The pause lives in the shared `api._funded_walk`, so these also pin that every
other book (no `loss_streak_limit`) walks exactly as before.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from app.labs.graduation import api, boost_lab, config

T0 = datetime(2026, 10, 12, 8, 0, tzinfo=UTC)
MIN = timedelta(minutes=1)
LOSS, WIN = -0.20, 0.20
RULES = boost_lab.WALK_RULES


def walk(trades, **kw):
    return api._funded_walk(trades, ticket=50.0, start=kw.pop("start", 1000.0), **kw)


def took(w):
    return [p is not None for p in w.pnl]


def losses(n, start=T0, every=10):
    """`n` funded trades, one after another, each closing at a loss."""
    return [(start + i * every * MIN, start + (i * every + 4) * MIN, LOSS) for i in range(n)]


# --- the ratio --------------------------------------------------------------

def row(quote, sol, liq):
    return SimpleNamespace(open_quote=quote, sol_usd_at_open=sol, liq_open_usd=liq)


def test_ratio_is_strictly_under_3_1_on_unrounded_entry_values():
    sol, liq = Decimal("100"), Decimal("20000")
    # market cap = quote x sol x 1e9; 3.1 x $20,000 = $62,000 -> quote 6.2e-7.
    at = Decimal("62000") / (sol * config.PUMP_SUPPLY)
    assert not boost_lab._entry_ratio_allowed(row(at, sol, liq))            # exactly 3.1
    assert boost_lab._entry_ratio_allowed(row(at - Decimal("1e-18"), sol, liq))
    assert not boost_lab._entry_ratio_allowed(row(at + Decimal("1e-18"), sol, liq))
    # No ceiling on the pool or the market cap themselves.
    assert boost_lab._entry_ratio_allowed(row(at * 100, sol, liq * 101))


def test_ratio_refuses_what_it_cannot_measure():
    for bad in (None, 0, -1, "x", Decimal("NaN"), float("inf")):
        assert not boost_lab._entry_ratio_allowed(row(bad, 100, 20000))
        assert not boost_lab._entry_ratio_allowed(row(Decimal("1e-7"), bad, 20000))
        assert not boost_lab._entry_ratio_allowed(row(Decimal("1e-7"), 100, bad))
    assert not boost_lab._entry_ratio_allowed(SimpleNamespace())


# --- the pause --------------------------------------------------------------

def test_three_funded_losses_pause_buys_for_an_hour_from_the_third_close():
    third_close = T0 + 24 * MIN
    trades = [*losses(3),
              (third_close + 59 * MIN, third_close + 63 * MIN, WIN),   # inside: refused
              (third_close + 60 * MIN, third_close + 64 * MIN, WIN)]   # the end: bought
    w = walk(trades, **RULES)
    assert took(w) == [True, True, True, False, True]
    assert (w.funded, w.paused, w.skipped) == (4, 1, 0)
    # Without the rule (every other book) nothing is refused.
    assert walk(trades).paused == 0 and walk(trades).funded == 5


def test_a_close_at_the_buys_own_instant_counts_after_the_buy():
    trades = losses(3)
    third_close = trades[-1][1]
    w = walk([*trades, (third_close, third_close + 4 * MIN, WIN),
              (third_close + MIN, third_close + 5 * MIN, WIN)], **RULES)
    assert took(w) == [True, True, True, True, False]


def test_closes_count_in_time_order_not_buy_order():
    """Two losses, then X (bought first, closes last, a loss) and Y (bought
    second, closes first, a win). In time order Y resets the streak before X
    lands, so there is no third loss in a row."""
    a = losses(2)
    t = a[-1][1] + MIN
    x = (t, t + 20 * MIN, LOSS)
    y = (t + MIN, t + 10 * MIN, WIN)
    after = (t + 30 * MIN, t + 34 * MIN, WIN)
    w = walk([*a, x, y, after], **RULES)
    assert all(took(w)) and w.paused == 0
    # Swap the outcomes: the loss now closes first (t+10), the third in a row,
    # so the buy at t+30 is inside the hour -- whichever was bought first.
    w = walk([*a, (t, t + 20 * MIN, WIN), (t + MIN, t + 10 * MIN, LOSS), after], **RULES)
    assert took(w) == [True, True, True, True, False]


def test_only_funded_trades_count_toward_the_streak():
    """$50 on $50: the overlapping loser is never bought, so it is no loss."""
    two = losses(2)
    t = two[-1][1] + MIN
    trades = [*two, (t, t + 10 * MIN, WIN), (t + MIN, t + 5 * MIN, LOSS),
              (t + 11 * MIN, t + 15 * MIN, LOSS), (t + 20 * MIN, t + 24 * MIN, WIN)]
    w = walk(trades, start=60.0, **RULES)
    assert took(w)[3] is False and w.skipped == 1
    assert w.paused == 0 and took(w)[-1]


def test_the_streak_starts_again_after_a_pause_and_after_a_win():
    first = losses(3)
    resume = first[-1][1] + 60 * MIN
    two_more = losses(2, start=resume)
    then = two_more[-1][1] + MIN
    w = walk([*first, *two_more, (then, then + 4 * MIN, WIN)], **RULES)
    assert all(took(w))                          # 2 losses after the pause are not 3
    w = walk([*losses(2), (T0 + 20 * MIN, T0 + 24 * MIN, WIN),
              *losses(2, start=T0 + 30 * MIN), (T0 + 60 * MIN, T0 + 64 * MIN, WIN)], **RULES)
    assert all(took(w))


def test_positions_held_through_a_pause_still_close():
    held = (T0 + 5 * MIN, T0 + 90 * MIN, WIN)    # bought before the third loss closes
    trades = sorted([*losses(3), held], key=lambda t: t[0])
    w = walk(trades, **RULES)
    assert all(took(w))
    assert round(w.cash, 6) == round(1000.0 + sum(p for p in w.pnl if p is not None), 6)


# --- one walk behind every figure -------------------------------------------

def rows(trades):
    return [SimpleNamespace(opened_at=o, closed_at=c, net_return=r,
                            impact_open=0, impact_close=0) for o, c, r in trades]


def test_each_fresh_start_resets_its_own_streak_and_pause():
    day2 = datetime(2026, 10, 12, 20, 0, tzinfo=UTC)     # 00:00 Dubai, 13 Oct
    first = losses(3, start=day2 - 40 * MIN)              # closes up to 20 min before
    late = (day2 + 5 * MIN, day2 + 9 * MIN, WIN)           # inside the full book's pause
    xs = rows([*first, late])
    starts = api._start_dates(xs, None, ticket=50.0, capital=250.0, now=day2 + 2 * 60 * MIN,
                              cents=Decimal("0.01"), **RULES)
    by_start = {s["start"]: s for s in starts}
    assert by_start[day2]["trades"] == 1                  # its own clean slate
    assert by_start[day2 - timedelta(days=1)]["trades"] == 3


def test_headline_days_and_closed_trades_agree():
    trades = [*losses(3), (T0 + 90 * MIN, T0 + 94 * MIN, WIN),
              (T0 + 25 * MIN, T0 + 29 * MIN, WIN)]
    xs = sorted(rows(trades), key=lambda r: r.opened_at)
    cents = Decimal("0.01")
    line = api._karthik_line(xs, None, size=50.0, capital=250.0, cents=cents, **RULES)
    w = api._funded_walk([(r.opened_at, r.closed_at, r.net_return, 0, 0) for r in xs],
                         None, ticket=50.0, start=250.0, **RULES)
    got = [(r, m) for r, m in zip(xs, w.pnl, strict=True) if m is not None]
    days = api._karthik_days(got, T0, 250.0, cents)
    assert line["trades"] == len(got) == w.funded and line["paused"] == w.paused == 1
    total = Decimal(str(sum(m for _, m in got))).quantize(cents)
    assert line["pnl_usd"] == total
    assert sum(Decimal(str(d["pnl_usd"])) for d in days) == total
