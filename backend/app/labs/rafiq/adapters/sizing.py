"""`earlysignal.execution.sizing` — the sizing envelope carried by a profile."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class SizingPolicy:
    """Five independent caps. The smallest binding one wins.

    Held as data rather than as a function so that a profile can be read and
    compared without running anything.
    """

    #: Fraction of equity risked on one trade, measured to the stop.
    risk_per_trade: Decimal
    #: Never take more than this fraction of the pool.
    max_pool_fraction: Decimal
    #: Never accept a quoted entry impact above this percent.
    max_impact_pct: Decimal
    #: Exits are assumed to happen into a market this much worse than entry.
    exit_stress_factor: Decimal
    #: The hard dollar ceiling, whatever the four fractions allow.
    max_notional_usd: Decimal
