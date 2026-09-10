"""STRATEGY E — ENSEMBLE_GUARDED

The synthesis, not a fifth point on the same grid.

WHAT "OUTSIDE THE BOX" ACTUALLY MEANS HERE
--------------------------------------------
A-D each fix one failure mode on the EXIT side: unbounded loss (A), zombie
duration (B), one-size-fits-all risk (C), whole-book daily damage (D). All
four could be perfectly implemented and a strategy could still lose, because
none of them touch the ENTRY side — they manage risk on a candidate, they do
not ask whether the candidate was ever a good idea.

The actual out-of-the-box move is not a new exit shape. It is refusing to
treat exits and entries as separable problems. E therefore requires BOTH:

  ENTRY:  independent evidence consensus (`evidence.consensus`) — at least
          two of {on-chain, DEX, social, safety} must agree, safety
          mandatory among them, and a manipulation-suspicious on-chain
          reading (`manipulation.assess`) vetoes outright regardless of how
          good everything else looks. This is the layer built after the
          MEMESCOPE forensic audit found that a strong-looking candidate can
          still be a rug with no visible precursor.

  EXIT:   A's hard stop, C's liquidity-derived stop distance and sizing, and
          D's mark-to-market daily breaker, composed together rather than
          picking one. B's aggressive 2h time-box is loosened here to 8h,
          because with a real stop already bounding the loss, holding longer
          for a winner to develop is no longer the risk it was for Karthik.

WHY THIS IS NOT CLAIMED TO "OVERCOME" A, B, C, OR D
-----------------------------------------------------
It cannot be claimed to beat them on this project's own evidence standard,
because no configuration in this entire project — including this one — has a
forward sample large enough to support that claim. What can honestly be said:
E is the only one of the five that gates entry quality at all, and the entry
side is exactly where the audit's dominant loss mode (rug pulls with no
observable precursor in market data alone) lives. Whether that produces a
better outcome is an empirical question `strategy_e_sensitivity.py` and a live
forward run address directly — see their outputs, not this docstring, for
whether it does.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from app.labs.rafiq.adapters.engine import ExitRules, SimConfig
from app.labs.rafiq.adapters.evidence import (
    Consensus,
    ConsensusPolicy,
    consensus,
)
from app.labs.rafiq.adapters.manipulation import Assessment, ManipulationPolicy
from app.labs.rafiq.adapters.manipulation import assess as assess_manipulation
from app.labs.rafiq.adapters.profiles import StrategyProfile
from app.labs.rafiq.adapters.sizing import SizingPolicy
from app.labs.rafiq.strategies.strategy_c_volatility_adjusted import (
    VolatilityAdjustedPolicy,
    sized_for_liquidity,
    stop_distance_for,
)
from app.labs.rafiq.strategies.strategy_d_daily_breaker import (
    DailyBreakerPolicy,
    DailyState,
)
from app.labs.rafiq.strategies.strategy_d_daily_breaker import (
    evaluate as evaluate_daily_breaker,
)

ENSEMBLE_GUARDED = StrategyProfile(
    lane="ensemble_guarded",
    # Placeholder exit shape for the fields every other profile carries. The
    # REAL exit distance is computed per-candidate by `exits_for()` below,
    # because C's whole point is that one fixed stop is wrong for every pool.
    exits=ExitRules(take_profit_mult=Decimal("1.30"), stop_mult=Decimal("0.88"),
                    trailing_frac=Decimal("0.20"), max_hold=timedelta(hours=8)),
    sizing=SizingPolicy(risk_per_trade=Decimal("0.01"), max_pool_fraction=Decimal("0.02"),
                        max_impact_pct=Decimal(1), exit_stress_factor=Decimal("0.25"),
                        max_notional_usd=Decimal(50)),
    sim=SimConfig(decision_latency=timedelta(seconds=15),
                  blackout_threshold=timedelta(minutes=5),
                  liquidity_collapse_frac=Decimal("0.20")),
    entry_threshold=Decimal(70),
    designed_breakeven_win_rate=Decimal("31.4"),  # informational; same shape as A
)

CONSENSUS_POLICY = ConsensusPolicy(min_confirming_streams=2, require_safety=True)
MANIPULATION_POLICY = ManipulationPolicy()
VOLATILITY_POLICY = VolatilityAdjustedPolicy()
DAILY_POLICY = DailyBreakerPolicy()


@dataclass(frozen=True)
class EntryDecision:
    admitted: bool
    reasons: tuple
    consensus: Consensus
    manipulation: Assessment


def evaluate_entry(streams, *, buyers=None, sellers=None, buys=None, sells=None,
                   volume_m5=None, market_cap=None, liquidity=None,
                   now) -> EntryDecision:
    """Both halves of the entry gate, neither optional.

    Manipulation is checked FIRST and vetoes independently of consensus
    breadth — a manipulated on-chain reading should not merely count as one
    non-confirming stream among several, it should stop the candidate outright,
    the same way a hard safety failure does.
    """
    manip = assess_manipulation(buyers=buyers, sellers=sellers, buys=buys,
                                sells=sells, volume_m5=volume_m5,
                                market_cap=market_cap, liquidity=liquidity,
                                policy=MANIPULATION_POLICY)
    agree = consensus(streams, now=now, policy=CONSENSUS_POLICY)

    reasons = list(agree.reasons)
    if manip.manipulated:
        reasons = [s.detail for s in manip.suspicious] + reasons

    admitted = agree.agreed and not manip.manipulated
    return EntryDecision(admitted, tuple(reasons), agree, manip)


def exits_for(liquidity_usd: Decimal | None, *,
             take_profit_mult: Decimal = Decimal("1.30"),
             max_hold: timedelta = timedelta(hours=8)) -> ExitRules | None:
    """C's liquidity-derived stop, wrapped as this candidate's actual exit
    rule. `None` if depth is unknown — an unpriceable pool gets no rule here,
    never a guessed one."""
    stop_pct = stop_distance_for(liquidity_usd, policy=VOLATILITY_POLICY)
    if stop_pct is None:
        return None
    return ExitRules(take_profit_mult=take_profit_mult,
                     stop_mult=(Decimal(100) - stop_pct) / 100,
                     trailing_frac=Decimal("0.20"),
                     max_hold=max_hold)


def size_for(equity: Decimal, liquidity_usd: Decimal | None,
            remaining_daily_risk: Decimal) -> Decimal:
    """C's liquidity-aware sizing, capped by whatever's left of today's risk
    budget once D's breaker's own limits are respected."""
    stop_pct = stop_distance_for(liquidity_usd, policy=VOLATILITY_POLICY)
    if stop_pct is None:
        return Decimal(0)
    base = sized_for_liquidity(equity, liquidity_usd, stop_pct=stop_pct,
                               max_notional_usd=ENSEMBLE_GUARDED.sizing.max_notional_usd)
    return min(base, remaining_daily_risk)


def portfolio_halted(daily_state: DailyState, *, now, cash: Decimal,
                     open_position_values) -> bool:
    """D wraps the whole strategy: once tripped, nothing above matters."""
    return evaluate_daily_breaker(daily_state, now=now, cash=cash,
                                  open_position_values=open_position_values,
                                  policy=DAILY_POLICY).halted
