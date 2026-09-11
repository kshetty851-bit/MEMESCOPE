"""`earlysignal.sim.engine` — the exit rule and the simulation's timing knobs.

Plain values. The runner reads them; they compute nothing themselves, which is
what keeps "what the rule says" and "what the runner did with it" two separate
things a reader can compare.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class ExitRules:
    """One position's four ways out.

    `trailing_frac` is a give-back fraction OF THE PEAK GAIN, not of the entry:
    0.20 means a position that reached +50% exits if it surrenders a fifth of
    that gain. It only ever protects profit that already exists — it never
    widens `stop_mult`, and it never removes it.

    `take_profit_mult` is None for a book with NO target — D2, and the second
    leg of C2. That is a real rule, not a missing value: the position can then
    only leave on the stop, the trail or the hold, which is the whole question
    those two books ask. It is never read as "unlimited upside with no exit".
    """

    take_profit_mult: Decimal | None
    stop_mult: Decimal
    trailing_frac: Decimal | None
    max_hold: timedelta


@dataclass(frozen=True, slots=True)
class SimConfig:
    """Timing assumptions the simulation makes explicit rather than implicit."""

    #: How long after an observation the decision is assumed to reach a market.
    decision_latency: timedelta
    #: A gap in the observation series longer than this is a blackout: nothing
    #: is acted on across it, because there was no market to act into.
    blackout_threshold: timedelta
    #: Liquidity falling to this fraction of its entry value is a collapse.
    liquidity_collapse_frac: Decimal
