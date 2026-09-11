"""The five v2 runners, as five values.

WHAT CHANGED FROM v1, AND WHY THE BOOKS ARE RENAMED
---------------------------------------------------
v1 spent three of its five books (A, C, D) on near-identical rule sets that
differed only in a liquidity-stop flag and a daily-breaker flag. All three
landed between -42% and -53%, so those two flags were shown to be irrelevant
and three books bought one answer.

v2 spends each book on a different question, and holds the entry gate constant
across four of them so the gate itself is what A2 measures against v1's A:

    A2  What does the entry gate alone do? Directly comparable to v1's A.
    B2  Does the gate push the best v1 book over the line?
    C2  Does scaling out beat a hard cap, given losers go to -100%?
    D2  Is the +30% cap cutting off the tail that pays for the rugs?
    E2  Does a much harder gate work, at a much lower trade count?

The codes are `A2`-`E2` rather than `A`-`E` because the ledger is keyed on
them and a v2 book is not a continuation of a v1 book. v1's rows were archived
and removed before these were activated; reusing the letters would have made
two different experiments share a column.

WHY VALUES AND NOT FIVE CLASSES
-------------------------------
Unchanged from v1, and still the point: one engine, five configurations, so a
difference in the record is a difference in the rule rather than a difference
in which copy of the tick loop was edited last.

A NOTE ON THE GATE THESE ALL CARRY
----------------------------------
`entry_gate.py` documents in full that the gate was replayed over v1's own
closed trades before any of this was written, and that the replay refuted the
premise. This is a forward run of a rule the backward evidence says does not
work. That is a deliberate choice, not an oversight.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from app.labs.rafiq import entry_gate
from app.labs.rafiq.adapters.engine import ExitRules
from app.labs.rafiq.adapters.profiles import StrategyProfile
from app.labs.rafiq.entry_gate import GateThresholds
from app.labs.rafiq.strategies import strategy_e_ensemble as e
from app.labs.rafiq.strategies.strategy_a_hard_stop import HARD_STOP_GUARD
from app.labs.rafiq.strategies.strategy_b_time_boxed import TIME_BOXED_EXIT
from app.labs.rafiq.strategies.strategy_c_volatility_adjusted import (
    sized_for_liquidity,
    stop_distance_for,
)
from app.labs.rafiq.strategies.strategy_e_ensemble import ENSEMBLE_GUARDED


@dataclass(frozen=True, slots=True)
class Leg:
    """One slice of a position, with its own way out.

    A single-leg book is the ordinary case and carries `fraction = 1`. C2 is
    the only book with two, which is the whole question it asks: half the
    position takes a fixed +30%, the other half has no target at all and
    leaves on the trail.

    The stop and the max hold are NOT per-leg — the spec gives C2 one stop and
    one hold, and a leg that could outlive its sibling would be a different
    experiment from the one being run.
    """

    fraction: Decimal
    take_profit_mult: Decimal | None
    trailing_frac: Decimal | None

    @property
    def canonical(self) -> dict:
        return {"fraction": str(self.fraction),
                "take_profit_mult": (None if self.take_profit_mult is None
                                     else str(self.take_profit_mult)),
                "trailing_frac": (None if self.trailing_frac is None
                                  else str(self.trailing_frac))}


#: C2 and D2 are exit shapes v1 never ran, so they are composed here from A's
#: sizing, simulation and entry threshold rather than given files of their own:
#: everything they specify, they specify in `exits` and `legs` below, and
#: borrowing the rest keeps them comparable to A2 on every axis but the one
#: under test. `take_profit_mult=None` on the profile is the honest value for
#: a book whose target lives on its legs — D2 has no target at all.
def _over_a(lane: str, *, stop_mult: Decimal, trailing_frac: Decimal | None,
            hold: timedelta, take_profit_mult: Decimal | None) -> StrategyProfile:
    return StrategyProfile(
        lane=lane,
        exits=ExitRules(take_profit_mult=take_profit_mult, stop_mult=stop_mult,
                        trailing_frac=trailing_frac, max_hold=hold),
        sizing=HARD_STOP_GUARD.sizing,
        sim=HARD_STOP_GUARD.sim,
        entry_threshold=HARD_STOP_GUARD.entry_threshold,
        designed_breakeven_win_rate=None,  # no fixed target: not defined here
    )


PARTIAL_EXIT = _over_a("partial_exit", stop_mult=Decimal("0.88"),
                       trailing_frac=Decimal("0.25"), hold=timedelta(hours=4),
                       take_profit_mult=None)

NO_CAP = _over_a("no_cap", stop_mult=Decimal("0.88"),
                 trailing_frac=Decimal("0.25"), hold=timedelta(hours=4),
                 take_profit_mult=None)


@dataclass(frozen=True, slots=True)
class LabStrategy:
    """One runner. `code` is what the ledger and the page call it."""

    code: str
    name: str
    #: The one-line question this book exists to answer. Shown on the page, so
    #: a reader never has to reconstruct why a column is there.
    question: str
    profile: StrategyProfile
    #: How the position is split at entry. One leg for every book but C2.
    legs: tuple[Leg, ...]
    #: The entry conditions. Identical across A2-D2 on purpose; E2 is stricter.
    gate: GateThresholds = entry_gate.DEFAULT
    #: True for E2: the stop distance and the size come from C's liquidity
    #: policy instead of the profile's flat `stop_mult`.
    liquidity_derived_risk: bool = False
    #: True for E2: the daily breaker is consulted before every entry.
    daily_breaker: bool = False
    #: True for E2: consensus + manipulation veto gate the entry.
    consensus_gate: bool = False

    @property
    def digest(self) -> str:
        """A stable hash of every constant that changes this strategy's result.

        Written onto the ledger row at activation and compared on every tick.
        Changing a number here is not a tweak — it is a new record. The gate
        thresholds are inside the hash because a gate that admits a different
        population produces a different book.
        """
        x, s = self.profile.exits, self.profile.sizing
        canonical = {
            "code": self.code, "lane": self.profile.lane,
            "take_profit_mult": (None if x.take_profit_mult is None
                                 else str(x.take_profit_mult)),
            "stop_mult": str(x.stop_mult),
            "trailing_frac": None if x.trailing_frac is None else str(x.trailing_frac),
            "max_hold_seconds": x.max_hold.total_seconds(),
            "legs": [leg.canonical for leg in self.legs],
            "risk_per_trade": str(s.risk_per_trade),
            "max_notional_usd": str(s.max_notional_usd),
            "entry_threshold": str(self.profile.entry_threshold),
            "entry_gate": self.gate.canonical,
            "liquidity_derived_risk": self.liquidity_derived_risk,
            "daily_breaker": self.daily_breaker,
            "consensus_gate": self.consensus_gate,
            "volatility_policy": (
                _volatility_canonical() if self.liquidity_derived_risk else None
            ),
            "breaker_policy": _breaker_canonical() if self.daily_breaker else None,
        }
        return hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


def _volatility_canonical() -> dict:
    p = e.VOLATILITY_POLICY
    return {"base_stop_pct": str(p.base_stop_pct),
            "reference_liquidity_usd": str(p.reference_liquidity_usd),
            "min_stop_pct": str(p.min_stop_pct), "max_stop_pct": str(p.max_stop_pct),
            "sensitivity": str(p.sensitivity)}


def _breaker_canonical() -> dict:
    p = e.DAILY_POLICY
    return {"max_daily_drawdown": str(p.max_daily_drawdown),
            "max_daily_realised_loss": str(p.max_daily_realised_loss)}


_WHOLE = Decimal(1)
_HALF = Decimal("0.5")

STRATEGIES: tuple[LabStrategy, ...] = (
    # A2 changes exactly one thing against v1's A: the gate. It is the control,
    # and if it does not clearly beat A's -53% the rest of this tells us little.
    LabStrategy("A2", "Gate only",
                "What does the entry gate alone do, against v1's A?",
                HARD_STOP_GUARD,
                legs=(Leg(_WHOLE, Decimal("1.30"), Decimal("0.20")),)),

    # B was v1's only book near breakeven before costs (-0.3%/trade gross over
    # 151 trades), so v2 treats B as the template rather than A. Same rules,
    # gate added.
    LabStrategy("B2", "Fast and cheap, gated",
                "Does the gate push the best v1 book over the line?",
                TIME_BOXED_EXIT,
                legs=(Leg(_WHOLE, Decimal("1.20"), None),)),

    # C2's two legs ARE the question. Half takes the same +30% A2 takes; half
    # has no target and can only leave on the trail, the stop or the hold.
    LabStrategy("C2", "Partial exit",
                "Does scaling out beat a hard cap, given losers go to -100%?",
                PARTIAL_EXIT,
                legs=(Leg(_HALF, Decimal("1.30"), None),
                      Leg(_HALF, None, Decimal("0.25")))),

    # v1 closed trades at +29% that would have run to +352%, +373%, +261%.
    # D2 removes the cap entirely and shortens the hold to pay for it.
    LabStrategy("D2", "No cap",
                "Is the +30% cap cutting off the tail that pays for the rugs?",
                NO_CAP,
                legs=(Leg(_WHOLE, None, Decimal("0.25")),)),

    # E2 keeps v1 E's three guards and runs the gate far stricter on top. It is
    # expected to trade rarely — v1's E closed nothing at all in 19 hours on
    # dev — and a low trade count is the cost of the question it asks.
    LabStrategy("E2", "Strict",
                "Does a much harder gate work, at a much lower trade count?",
                ENSEMBLE_GUARDED,
                legs=(Leg(_WHOLE, Decimal("1.30"), Decimal("0.20")),),
                gate=entry_gate.STRICT,
                liquidity_derived_risk=True, daily_breaker=True,
                consensus_gate=True),
)

BY_CODE = {s.code: s for s in STRATEGIES}


def stop_pct_for(strategy: LabStrategy,
                 liquidity_usd: Decimal | None) -> Decimal | None:
    """Percent stop distance for this candidate, or None if it cannot be set.

    E2 defers to Rafiq's `stop_distance_for`, which returns None for an
    unpriceable pool. None means "cannot size this trade" — the caller declines
    it rather than reaching for a fallback number.
    """
    if strategy.liquidity_derived_risk:
        return stop_distance_for(liquidity_usd, policy=e.VOLATILITY_POLICY)
    return (Decimal(1) - strategy.profile.exits.stop_mult) * 100


def notional_for(strategy: LabStrategy, *, equity: Decimal,
                 liquidity_usd: Decimal | None,
                 stop_pct: Decimal | None) -> Decimal:
    """What this strategy stakes on this candidate, across all its legs.

    The figure is the WHOLE position. C2 splits it afterwards; it is not sized
    per leg, because a gate applied to half a position is a different gate, and
    two $25 buys pay less impact than the one $50 buy this book actually makes.
    """
    if stop_pct is None or stop_pct <= 0:
        return Decimal(0)
    cap = strategy.profile.sizing.max_notional_usd
    if strategy.liquidity_derived_risk:
        return sized_for_liquidity(
            equity, liquidity_usd, stop_pct=stop_pct,
            risk_per_trade=strategy.profile.sizing.risk_per_trade,
            max_notional_usd=cap)
    if liquidity_usd is None or liquidity_usd <= 0:
        return Decimal(0)
    return min(equity * strategy.profile.sizing.risk_per_trade / (stop_pct / 100), cap)


def max_hold_for(strategy: LabStrategy) -> timedelta:
    return strategy.profile.exits.max_hold


assert {s.code for s in STRATEGIES} == {"A2", "B2", "C2", "D2", "E2"}, \
    "the registry must hold exactly the five v2 books"
assert all(sum((leg.fraction for leg in s.legs), Decimal(0)) == 1
           for s in STRATEGIES), \
    "every book's legs must account for exactly the whole position"
