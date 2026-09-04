"""The thirty-day band, and the cases where it must refuse to draw one.

Most of these are about REFUSING. A projection is the single most dangerous
number this platform can display: it is the one a reader converts directly into
a funding decision, and the history here is unambiguous about what a small
sample does. V6-07 showed a 3.0 profit factor on 23 trades, was nearly funded on
that basis, and ended at -25% having peaked at +65%.

So the tests that matter are not "does it compute a percentile" but "does it
stay silent when the sample cannot support one", and "does it always put the
random control beside the leader".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.lab import projection

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
START = NOW - timedelta(days=10)
FLOOR = Decimal("80")
D = Decimal


def run(pnls, equity=D("100"), first=START, seed=0) -> projection.Projection:
    return projection.project(pnls=pnls, equity_now=equity, first_trade_at=first,
                              now=NOW, failure_floor=FLOOR, seed=seed)


# --------------------------------------------------------------------------
# refusing
# --------------------------------------------------------------------------


@pytest.mark.parametrize("n", [0, 1, 23, projection.MIN_TRADES - 1])
def test_it_refuses_below_the_minimum_sample(n: int) -> None:
    """23 is not an arbitrary example: it is what V6-07 had when it looked like
    a 3.0 profit factor and was nearly funded."""
    p = run([D("1")] * n)
    assert p.projectable is False
    assert p.p50 is None and p.p_profit is None
    assert str(projection.MIN_TRADES) in p.reason


def test_the_refusal_says_how_many_trades_there_are() -> None:
    """A reader must be able to see how far off the sample is, not just that it
    is insufficient."""
    p = run([D("1")] * 12)
    assert "12" in p.reason


def test_it_refuses_without_a_start_date() -> None:
    """The rate is trades per DAY. With no first trade there is no denominator,
    and inventing one would invent the whole projection."""
    p = run([D("1")] * 80, first=None)
    assert p.projectable is False


# --------------------------------------------------------------------------
# the band
# --------------------------------------------------------------------------


def test_a_losing_book_projects_a_losing_band() -> None:
    """Four wins of $1 against one loss of $5 — the shape every V6 strategy
    had, and the one a win RATE flatters."""
    p = run(([D("1")] * 4 + [D("-5")]) * 20)
    assert p.projectable is True
    assert p.p50 < D("100")
    assert p.p_profit < 0.25


def test_a_winning_book_projects_a_winning_band() -> None:
    p = run([D("1")] * 40 + [D("-0.5")] * 40)
    assert p.p50 > D("100")
    assert p.p_profit > 0.75


def test_the_percentiles_are_ordered() -> None:
    p = run(([D("3")] * 3 + [D("-5")]) * 25)
    assert p.p10 <= p.p50 <= p.p90


def test_a_wide_book_gives_a_wide_band() -> None:
    """Two books with the SAME mean and different spread must not project the
    same confidence. A point estimate would report them identically."""
    tight = run([D("0.1"), D("-0.1")] * 40)
    wide = run([D("10"), D("-10")] * 40)
    assert (wide.p90 - wide.p10) > (tight.p90 - tight.p10) * 10


def test_ruin_is_reported_not_just_profit() -> None:
    """"Probability of profit" alone hides the tail that ends the experiment."""
    p = run(([D("1")] * 4 + [D("-5")]) * 20)
    assert p.p_ruin is not None and p.p_ruin > 0


# --------------------------------------------------------------------------
# stability and honesty
# --------------------------------------------------------------------------


def test_the_same_book_gives_the_same_band_every_time() -> None:
    """A band that moved between page loads would invite refreshing until it
    looked good."""
    book = ([D("2")] * 3 + [D("-4")]) * 20
    assert run(book).as_dict() == run(book).as_dict()


def test_the_projection_rate_reflects_observed_trading() -> None:
    """80 trades over 10 days is 8/day, so thirty days is ~240."""
    p = run([D("0.5")] * 80)
    assert 7.5 <= p.trades_per_day <= 8.5
    assert 230 <= p.projected_trades <= 250


def test_it_always_carries_the_warning_about_what_it_is() -> None:
    """The V6 tournament peaked above its start and then died. A projection
    taken at the peak would have pointed the wrong way with total confidence,
    and the output has to say so where the number is read."""
    p = run([D("1")] * 60)
    joined = " ".join(p.notes).lower()
    assert "not a forecast" in joined
    assert "random control" in joined


def test_it_reports_the_sample_it_used() -> None:
    p = run([D("1")] * 60)
    assert p.trades_observed == 60
    assert "60" in " ".join(p.notes)
