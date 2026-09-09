"""Strategy B: nothing outlives two hours.

The defining claim is a bound, so the test is a bound: across a grid of price
paths — mooning, dead flat, bleeding, and a price that never prints at all —
no position is still open at 2h. Testing one happy path would prove only that
one happy path exits.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.labs.rafiq.engine import Geometry, Mark, evaluate
from app.labs.rafiq.strategies.strategy_b_time_boxed import (
    TIME_BOXED_EXIT,
    max_capital_days_at_risk,
)

T0 = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
ENTRY = Decimal(1)


def geometry() -> Geometry:
    x = TIME_BOXED_EXIT.exits
    return Geometry(entry_price=ENTRY, stop_price=ENTRY * x.stop_mult,
                    target_price=ENTRY * x.take_profit_mult,
                    trailing_frac=x.trailing_frac, max_hold=x.max_hold,
                    opened_at=T0)


def test_nothing_survives_two_hours_at_any_price() -> None:
    at = T0 + timedelta(hours=2)
    for price in ("0.95", "1.00", "1.05", "1.19", "0.91"):
        # Prices deliberately between the stop (0.90) and target (1.20), so
        # only the time box can be what closes them.
        decision = evaluate(geometry(), Mark(Decimal(price), at),
                            peak_price=Decimal(price),
                            last_mark_price=Decimal(price), now=at)
        assert decision is not None, f"{price} still open at 2h"
        assert decision.reason == "max_hold"


def test_a_stale_mark_still_closes_at_the_box() -> None:
    """B exists to stop capital sitting in a zombie. A mark that is an hour
    old is still the best price anyone observed, and exiting at it is the
    point of the rule — carrying the position further is the failure."""
    at = T0 + timedelta(hours=3)
    decision = evaluate(geometry(),
                        Mark(Decimal("0.95"), T0 + timedelta(hours=2)),
                        peak_price=ENTRY, last_mark_price=Decimal("0.95"), now=at)
    assert decision is not None
    assert decision.reason == "max_hold"
    assert "old" in decision.evidence


def test_before_the_box_a_quiet_position_is_held() -> None:
    """The bound is a ceiling, not a schedule: nothing forces an early exit."""
    at = T0 + timedelta(hours=1, minutes=59)
    assert evaluate(geometry(), Mark(Decimal("0.95"), at), peak_price=ENTRY,
                    last_mark_price=Decimal("0.95"), now=at) is None


def test_a_token_that_stops_printing_still_hits_the_box() -> None:
    """The zombie case, and the one B exists for. No current market at all —
    not a stale print, NOTHING — and the position still closes at the box, at
    the last price anyone actually observed.

    Found by running the lab rather than by reading it: an earlier version
    returned `None` whenever the mark was missing, so a token that simply
    stopped printing outlived the 2-hour box for ever.
    """
    at = T0 + timedelta(hours=5)
    decision = evaluate(geometry(), None, peak_price=ENTRY,
                        last_mark_price=Decimal("0.93"), now=at)
    assert decision is not None
    assert decision.reason == "max_hold"
    assert decision.fill_price == Decimal("0.93")
    assert "no current market" in decision.evidence


def test_a_position_never_priced_at_all_is_held_not_zeroed() -> None:
    """The other half. With nothing ever observed there is no price to exit
    at, and inventing one — $0 above all — would be a claim nobody measured."""
    at = T0 + timedelta(hours=5)
    assert evaluate(geometry(), None, peak_price=ENTRY,
                    last_mark_price=None, now=at) is None


def test_max_capital_days_at_risk_is_two_hours() -> None:
    assert max_capital_days_at_risk(1) == Decimal(2) / 24


def test_b_has_no_trail() -> None:
    """`trailing_frac is None` is the spec: the time box IS the discipline."""
    assert TIME_BOXED_EXIT.exits.trailing_frac is None
    assert TIME_BOXED_EXIT.exits.max_hold == timedelta(hours=2)
