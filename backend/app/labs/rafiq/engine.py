"""The exit evaluator. Pure — no session, no clock of its own, no I/O.

It is separate from `service.py` so the four ways out can be tested against
constructed prices rather than against a database, and so a reader can check
what the rule does without reading what the runner does with it.

ORDER, AND WHY IT IS THIS ORDER
-------------------------------
    glitch guard -> stop -> take profit -> trailing -> max hold

A position with no `target_price` simply skips the take-profit rung; the order
of the rest is unchanged, so a no-target book and a capped one are still the
same evaluator seen from two configurations.

The stop is checked first because it is the worst case, and a print that
satisfies both the stop and the target is not a market, it is a glitch. Take
profit precedes the trail because a position AT its target took its target;
the trail exists for winners that never reach it.

TWO GUARDS THAT ARE NOT OPTIONAL
--------------------------------
* **Glitch band.** A print more than 3x off the 10-minute rolling median does
  not fill in EITHER direction. Symmetric on purpose: an implausible crash is
  no more sellable than an implausible spike, and treating only spikes as
  suspect lets a position "stop out" at a price nobody could have sold into.
* **Fill-drift cap.** A level exit fills at the print, but never better than
  `trigger x 1.15`. A gap-up print is a real fill; an unlimited one is fiction.
  This project has twice published a number that a missing cap produced.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.labs.rafiq.config import FILL_DRIFT_CAP, GLITCH_BAND


@dataclass(frozen=True, slots=True)
class Geometry:
    """A position's exit rule, frozen at entry."""

    entry_price: Decimal
    stop_price: Decimal
    #: None for a book with no take profit (D2, and C2's second leg).
    target_price: Decimal | None
    trailing_frac: Decimal | None
    max_hold: timedelta
    opened_at: datetime


@dataclass(frozen=True, slots=True)
class Mark:
    """What the market last said."""

    price: Decimal
    observed_at: datetime
    median_price_10m: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Exit:
    #: `stop` | `take_profit` | `trailing` | `max_hold`.
    reason: str
    #: What the position is assumed to fill at. May differ from `observed`.
    fill_price: Decimal
    observed_price: Decimal
    evidence: str


def off_band(price: Decimal, median: Decimal | None) -> bool:
    """True when a print is a glitch rather than a market you can trade into."""
    if median is None or median <= 0 or price <= 0:
        return False
    return price > median * GLITCH_BAND or price < median / GLITCH_BAND


def evaluate(geometry: Geometry, mark: Mark | None, *, peak_price: Decimal,
             last_mark_price: Decimal | None, now: datetime) -> Exit | None:
    """The one decision. None means hold.

    `mark` is None when nothing priced the token at this tick. That is NOT an
    exit at zero — this project closed real positions at $0 for ever on a
    single unpriced observation, and 6.9% of those tokens were still trading.

    But it is not an exit at never, either. A token that simply stops printing
    is precisely the zombie Strategy B exists to kill, so once the max hold has
    passed the position closes at `last_mark_price` — the last price anyone
    actually observed — and says so in its evidence. With nothing ever
    observed there is no price to exit at, and only then does it hold.
    """
    age = now - geometry.opened_at
    expired = age >= geometry.max_hold

    if mark is None:
        if expired and last_mark_price is not None:
            return Exit("max_hold", last_mark_price, last_mark_price,
                        f"held {age} at or past max {geometry.max_hold}; "
                        "no current market — exited at the last observed price "
                        f"{last_mark_price:.10f}, priced against the pool's "
                        "depth at entry")
        return None

    if off_band(mark.price, mark.median_price_10m):
        # A glitch print is not a market. Not even the max hold acts on one:
        # exiting at a price nobody could trade is worse than holding a day.
        return None

    price = mark.price

    if price <= geometry.stop_price:
        # Gap-through is real: the fill is the print, not the nominal level.
        # `worst_case_loss_pct` in Strategy A is explicit that it describes the
        # DESIGNED bound, not a promise about execution.
        gapped = price < geometry.stop_price
        return Exit("stop", price, price,
                    f"price {price:.10f} at or below stop {geometry.stop_price:.10f}"
                    + (" (gapped through)" if gapped else ""))

    if geometry.target_price is not None and price >= geometry.target_price:
        capped = min(price, geometry.target_price * FILL_DRIFT_CAP)
        return Exit("take_profit", capped, price,
                    f"price {price:.10f} at or above target "
                    f"{geometry.target_price:.10f}"
                    + (f", fill capped at {capped:.10f}" if capped < price else ""))

    if geometry.trailing_frac is not None and peak_price > geometry.entry_price:
        gain = peak_price - geometry.entry_price
        floor = peak_price - gain * geometry.trailing_frac
        if price <= floor:
            return Exit("trailing", price, price,
                        f"gave back {geometry.trailing_frac:.0%} of a peak gain "
                        f"to {peak_price:.10f}; floor {floor:.10f}")

    if expired:
        stale = (now - mark.observed_at).total_seconds()
        return Exit("max_hold", price, price,
                    f"held {age} at or past max {geometry.max_hold}"
                    + (f"; mark {stale:.0f}s old" if stale > 900 else ""))

    return None
