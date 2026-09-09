"""`earlysignal.strategy.profiles` — one strategy as a value."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.labs.rafiq.adapters.engine import ExitRules, SimConfig
from app.labs.rafiq.adapters.sizing import SizingPolicy


@dataclass(frozen=True, slots=True)
class StrategyProfile:
    """Everything that decides what a strategy does, in one immutable value.

    `designed_breakeven_win_rate` is INFORMATIONAL and Rafiq's files say so:
    it is the win rate the exit geometry would need to break even before costs,
    not a claim about the win rate the strategy will achieve.
    """

    lane: str
    exits: ExitRules
    sizing: SizingPolicy
    sim: SimConfig
    #: Minimum opportunity score (0-100) a candidate must carry to be admitted.
    entry_threshold: Decimal
    designed_breakeven_win_rate: Decimal | None = None
