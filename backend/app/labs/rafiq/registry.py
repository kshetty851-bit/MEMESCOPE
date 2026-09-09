"""The five runners, as five values.

WHY VALUES AND NOT FIVE CLASSES
-------------------------------
A-E differ in exactly four ways: which profile they carry, whether the stop is
flat or liquidity-derived, whether the daily breaker gates entry, and whether
there is an entry gate beyond the score threshold. Five near-identical runner
classes would be five copies of the same tick loop, and the first time one was
edited they would stop being comparable — which is the only thing this lab
exists to do. One engine, five configurations, so a difference in the record
is a difference in the rule.

Each value below points at Rafiq's own module for everything it decides. No
constant is restated here.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from app.labs.rafiq.adapters.profiles import StrategyProfile
from app.labs.rafiq.strategies import strategy_e_ensemble as e
from app.labs.rafiq.strategies.strategy_a_hard_stop import HARD_STOP_GUARD
from app.labs.rafiq.strategies.strategy_b_time_boxed import TIME_BOXED_EXIT
from app.labs.rafiq.strategies.strategy_c_volatility_adjusted import (
    sized_for_liquidity,
    stop_distance_for,
)
from app.labs.rafiq.strategies.strategy_e_ensemble import ENSEMBLE_GUARDED

#: C has no `StrategyProfile` of its own — it is a sizing and stop-distance
#: policy, not an exit shape. To run it as a strategy it needs the missing
#: fields, and they are taken from A rather than invented: A is the profile C's
#: `base_stop_pct = 12` was written against ("baseline stop at the reference
#: liquidity depth", the same -12% A fixes), so borrowing A's target, trail,
#: hold and threshold changes nothing C specifies and guesses nothing it does
#: not. What C overrides — the stop distance and the size — it overrides in its
#: own file, through `stop_distance_for` and `sized_for_liquidity`.
VOLATILITY_ADJUSTED_RISK = StrategyProfile(
    lane="volatility_adjusted_risk",
    exits=HARD_STOP_GUARD.exits,
    sizing=HARD_STOP_GUARD.sizing,
    sim=HARD_STOP_GUARD.sim,
    entry_threshold=HARD_STOP_GUARD.entry_threshold,
    designed_breakeven_win_rate=HARD_STOP_GUARD.designed_breakeven_win_rate,
)

#: D is a portfolio-level halt, not an exit shape either. It is run over A's
#: geometry for the same reason, so the D column answers exactly one question:
#: what does adding the daily breaker to A do?
DAILY_DRAWDOWN_BREAKER = StrategyProfile(
    lane="daily_drawdown_breaker",
    exits=HARD_STOP_GUARD.exits,
    sizing=HARD_STOP_GUARD.sizing,
    sim=HARD_STOP_GUARD.sim,
    entry_threshold=HARD_STOP_GUARD.entry_threshold,
    designed_breakeven_win_rate=HARD_STOP_GUARD.designed_breakeven_win_rate,
)


@dataclass(frozen=True, slots=True)
class LabStrategy:
    """One runner. `code` is what the ledger and the page call it."""

    code: str
    name: str
    profile: StrategyProfile
    #: True for C and E: the stop distance and the size come from C's
    #: liquidity policy instead of the profile's flat `stop_mult`.
    liquidity_derived_risk: bool = False
    #: True for D and E: the daily breaker is consulted before every entry.
    daily_breaker: bool = False
    #: True for E only: consensus + manipulation veto gate the entry.
    consensus_gate: bool = False

    @property
    def digest(self) -> str:
        """A stable hash of every constant that changes this strategy's result.

        Written onto the ledger row at activation and compared on every tick.
        Changing a number here is not a tweak — it is a new record.
        """
        x, s = self.profile.exits, self.profile.sizing
        canonical = {
            "code": self.code, "lane": self.profile.lane,
            "take_profit_mult": str(x.take_profit_mult),
            "stop_mult": str(x.stop_mult),
            "trailing_frac": None if x.trailing_frac is None else str(x.trailing_frac),
            "max_hold_seconds": x.max_hold.total_seconds(),
            "risk_per_trade": str(s.risk_per_trade),
            "max_notional_usd": str(s.max_notional_usd),
            "entry_threshold": str(self.profile.entry_threshold),
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


STRATEGIES: tuple[LabStrategy, ...] = (
    LabStrategy("A", "Hard stop guard", HARD_STOP_GUARD),
    LabStrategy("B", "Time-boxed exit", TIME_BOXED_EXIT),
    LabStrategy("C", "Volatility-adjusted risk", VOLATILITY_ADJUSTED_RISK,
                liquidity_derived_risk=True),
    LabStrategy("D", "Daily drawdown breaker", DAILY_DRAWDOWN_BREAKER,
                daily_breaker=True),
    LabStrategy("E", "Ensemble guarded", ENSEMBLE_GUARDED,
                liquidity_derived_risk=True, daily_breaker=True,
                consensus_gate=True),
)

BY_CODE = {s.code: s for s in STRATEGIES}


def stop_pct_for(strategy: LabStrategy,
                 liquidity_usd: Decimal | None) -> Decimal | None:
    """Percent stop distance for this candidate, or None if it cannot be set.

    C and E defer to Rafiq's `stop_distance_for`, which returns None for an
    unpriceable pool. None means "cannot size this trade" — the caller declines
    it rather than reaching for a fallback number.
    """
    if strategy.liquidity_derived_risk:
        return stop_distance_for(liquidity_usd, policy=e.VOLATILITY_POLICY)
    return (Decimal(1) - strategy.profile.exits.stop_mult) * 100


def notional_for(strategy: LabStrategy, *, equity: Decimal,
                 liquidity_usd: Decimal | None,
                 stop_pct: Decimal | None) -> Decimal:
    """What this strategy stakes on this candidate.

    C and E size through Rafiq's `sized_for_liquidity`, so a wider stop means a
    smaller notional and the dollar risk stays put. A, B and D use their
    profile's own `risk_per_trade` against their flat stop, which is the same
    arithmetic with a constant stop distance.
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


assert {s.code for s in STRATEGIES} == {"A", "B", "C", "D", "E"}, \
    "the registry must hold exactly Rafiq's five strategies"
