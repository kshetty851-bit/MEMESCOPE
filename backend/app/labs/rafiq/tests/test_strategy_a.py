"""Strategy A: the loss cap is the whole claim.

Its docstring does the arithmetic in the open:

    0.534 * (+41%) - 0.466 * (100%) = -24.3% per trade

and says a stop turns that into a bounded number. Both halves are tested here,
because a claim in a docstring with no test behind it is a claim.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from app.labs.rafiq.strategies.strategy_a_hard_stop import (
    HARD_STOP_GUARD,
    worst_case_loss_pct,
)

WIN_RATE = Decimal("0.534")
AVG_WINNER = Decimal(41)


def expectancy(loss_pct: Decimal) -> Decimal:
    return WIN_RATE * AVG_WINNER - (1 - WIN_RATE) * loss_pct


def test_capped_loss_makes_expectancy_positive() -> None:
    """53.4% win rate, +41% winners, -12% losers: positive, before costs."""
    assert expectancy(worst_case_loss_pct()) > 0


def test_uncapped_loss_makes_expectancy_negative() -> None:
    """The same population with no stop is the Karthik wallet's own result."""
    assert expectancy(Decimal(100)) < 0
    # And it lands near the -24.3% the docstring states.
    assert abs(expectancy(Decimal(100)) - Decimal("-24.712")) < Decimal("0.01")


def test_worst_case_loss_is_twelve_percent() -> None:
    """The stop is 0.88, so the designed bound is 12%. Not 'about 12'."""
    assert worst_case_loss_pct() == Decimal(12)


def test_constants_are_rafiqs() -> None:
    """A regression guard on the spec itself: these five numbers ARE the
    strategy, and a silent edit to one of them is a different experiment."""
    x = HARD_STOP_GUARD.exits
    assert x.take_profit_mult == Decimal("1.30")
    assert x.stop_mult == Decimal("0.88")
    assert x.trailing_frac == Decimal("0.20")
    assert x.max_hold == timedelta(hours=12)
    assert HARD_STOP_GUARD.sizing.max_notional_usd == Decimal(50)
