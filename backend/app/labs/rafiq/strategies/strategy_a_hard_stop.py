"""STRATEGY A — HARD_STOP_GUARD

Fixes exactly one thing: the Karthik Paper Wallet's defining defect.

THE EVIDENCE THIS RESPONDS TO
------------------------------
Karthik ran $10/token, take-profit 1.25x, NO STOP LOSS, no time exit, for 18+
days: $1,000 -> $33.69 (-96.63%). 145 of 311 closed trades (46.6%) closed
`Dead/zero` — a full -100% each, because nothing ever forced them out earlier.
Every one of its 20 open positions at snapshot time was already down 85-99%
and still sitting in the book, unprotected, because there was no rule that
could close them.

Expectancy with a 53.4% win rate, wins averaging +41%, losses averaging -100%:

    0.534 * (+41%) - 0.466 * (100%) = -24.3% per trade

That number is close to the platform's own realised -$2.49/trade on a $10
stake. It is a mechanical, arithmetic result of the payoff shape, not bad luck.

THE FIX
-------
A stop loss bounds the loss per trade to a KNOWN, small number instead of an
unbounded, usually-total one. This is the single highest-leverage change
available, because it is the only one of the four that changes what "the
worst trade can do to you" even means.

With a 12% stop instead of "no stop", the same 46.6% base rate of tokens that
eventually die produces at most a -12% loss on the position, not -100% —
an 88% reduction in what each dead token costs, in exchange for nothing but
occasionally exiting a token early that would have recovered.

A trailing component is included so that a winner already up meaningfully does
not have to give it ALL back before something acts — but the trail only
starts protecting profit that already exists; it never widens the initial
stop, and it never removes it.

WHAT THIS DOES NOT CLAIM
------------------------
No specific win rate. No specific daily return. This changes the SHAPE of the
loss distribution; it does not guarantee the strategy is profitable. Whether
it is has to be measured on real forward data, same as everything else in this
project.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from app.labs.rafiq.adapters.costs import CostModel
from app.labs.rafiq.adapters.engine import ExitRules, SimConfig
from app.labs.rafiq.adapters.profiles import StrategyProfile
from app.labs.rafiq.adapters.sizing import SizingPolicy

MODEL = CostModel(swap_fee_bps=Decimal(30))

HARD_STOP_GUARD = StrategyProfile(
    lane="hard_stop_guard",
    exits=ExitRules(
        take_profit_mult=Decimal("1.30"),      # +30%, same target family as SWING
        stop_mult=Decimal("0.88"),             # HARD stop at -12%. THE fix.
        trailing_frac=Decimal("0.20"),         # once ahead, protect 80% of the peak gain
        max_hold=timedelta(hours=12),          # nothing is left open indefinitely
    ),
    sizing=SizingPolicy(
        risk_per_trade=Decimal("0.01"),
        max_pool_fraction=Decimal("0.02"),
        max_impact_pct=Decimal(1),
        exit_stress_factor=Decimal("0.25"),
        max_notional_usd=Decimal(50),
    ),
    sim=SimConfig(decision_latency=timedelta(seconds=15),
                  blackout_threshold=timedelta(minutes=5),
                  liquidity_collapse_frac=Decimal("0.20")),
    entry_threshold=Decimal(70),
    designed_breakeven_win_rate=Decimal("31.4"),  # (12+0.9)/(30+12+0.9), informational
)


def worst_case_loss_pct(profile: StrategyProfile = HARD_STOP_GUARD) -> Decimal:
    """The number that matters most: how much can ONE bad trade cost, at worst,
    assuming the stop fires at its nominal level (real fills can gap through
    this — see sim/engine.py's gap-through handling; this is the DESIGNED
    bound, not a promise about execution)."""
    return (Decimal(1) - profile.exits.stop_mult) * 100
