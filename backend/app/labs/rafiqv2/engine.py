"""The one exit rule all six books run. Pure: no session, no clock, no I/O.

    stop -> profit lock -> scale out -> runner trail -> rug ladder -> max hold

That is the books' own `_ordering`, with the runner's 45% trail placed after
the scale-out that creates the runner (D2 never scales out, so its whole
position is the runner from entry). The lock sits above the trail until a
peak near 3x, so the trail only binds on very large runners.

Multiples are against `entry_price`, the price actually paid after fee and
impact — the lab's convention for every stop and target. So "breakeven at
120s" means the position must have earned back its entry cost by then.

The caller hands this only a tradeable, on-band price. A glitch print, a pool
that reads gone and a pool nothing has priced are the service's to handle,
because each of those is a fact about the feed, not about the rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.labs.rafiqv2.base.config import FILL_DRIFT_CAP
from app.labs.rafiqv2.config import Book
from app.labs.rafiqv2.strategy_common import FastRugGate, ProfitLock

#: The partial sale. Never an `exit_reason`: the row stays open.
SCALE_OUT = "scale_out"
LOCK = "profit_lock"


@dataclass(frozen=True)
class Decision:
    #: An exit reason, or `SCALE_OUT`.
    reason: str
    #: Of the ORIGINAL quantity: 0.8 for a scale-out, else all that is left.
    fraction: Decimal
    fill: Decimal
    evidence: str


def decide(book: Book, *, entry_price: Decimal, opened_at: datetime,
           peak_price: Decimal, scaled_out: bool, fraction_open: Decimal,
           rug_strictness: Decimal, lock_giveback: Decimal, price: Decimal,
           now: datetime) -> Decision | None:
    """None means hold. `peak_price` must already include `price`."""
    m = price / entry_price
    age = now - opened_at
    seen = f"{m:.4f}x entry after {age.total_seconds():.0f}s"

    def sell(reason: str, why: str) -> Decision:
        # Every full exit fills at the print: a gap through a level is real.
        return Decision(reason, fraction_open, price, f"{why}; {seen}")

    if m <= book.stop:
        return sell("stop", f"at or under the {book.stop}x stop")

    lock = ProfitLock(giveback=lock_giveback, ladder=book.lock_ladder)
    lock.observe(peak_price / entry_price)
    if lock.breached(m):
        return sell(LOCK, f"at or under the lock floor {lock.floor_multiple:.4f}x "
                          f"set by a {peak_price / entry_price:.4f}x peak")

    if book.scale_out_at is not None and not scaled_out and m >= book.scale_out_at:
        # A level sale: a gap-up print is a real fill, an unlimited one is not.
        fill = min(price, entry_price * book.scale_out_at * FILL_DRIFT_CAP)
        return Decision(SCALE_OUT, book.scale_out_fraction, fill,
                        f"{book.scale_out_fraction:.0%} sold at the "
                        f"{book.scale_out_at}x scale-out; {seen}")

    runner = scaled_out or book.scale_out_at is None
    if runner and price <= peak_price * (1 - book.runner_trail):
        return sell("runner_trail", f"{book.runner_trail:.0%} off the peak "
                                    f"{peak_price / entry_price:.4f}x")

    rung = FastRugGate(book.rug_ladder, rug_strictness).check(age=age, multiple=m)
    if rung is not None:
        return sell(rung, f"under the {rung} checkpoint (strictness "
                          f"{rug_strictness:+})")

    if age >= book.max_hold:
        return sell("max_hold", f"held to the {book.max_hold} box")
    return None
