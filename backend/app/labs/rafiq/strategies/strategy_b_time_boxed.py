"""STRATEGY B — TIME_BOXED_EXIT

Fixes the second defect visible in the Karthik data: capital trapped for
days in positions that were never going to recover.

THE EVIDENCE THIS RESPONDS TO
------------------------------
Karthik's open-positions table (20 rows) shows ages up to 18d 5h, values down
to $0.09-$1.47 on a $10 stake, still open because nothing forces a decision.
Its own average-hold figure is "1d 0h" for CLOSED trades — but that average
hides a wide spread: some trades resolve via take-profit in minutes, while
dead ones can apparently sit for over two weeks before being marked
`Dead/zero`. Every day a token sits at 2% of its entry value with no time
exit is a day of capital that could have been redeployed into a fresh
opportunity instead.

THE FIX
-------
A SHORT, hard maximum hold. If the thesis (momentum, buy pressure, liquidity
health) hasn't produced a profitable move within a tight window, the position
exits at whatever price is observed then — win, loss, or flat — rather than
being carried indefinitely on hope.

This is deliberately the SAME mechanism as SCALP in `profiles.py`
(45-minute max hold), tightened further, because the Karthik data's own
`Detected -> Track Record -> Entry` timestamps show most tokens' meaningful
price action (if any) happens within the first hour: entries fill 20-60
seconds after detection, and by the time a position is a day old it has
almost always already found its winner-or-loser path.

WHY THIS IS NOT THE SAME AS A STOP LOSS
-----------------------------------------
A stop (Strategy A) bounds LOSS SIZE. A time exit bounds LOSS DURATION. A
token that has quietly bled to -40% over six hours with no stop hit yet is
still tying up capital and optionality; the time exit forces a decision on it
regardless of price.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from app.labs.rafiq.adapters.engine import ExitRules, SimConfig
from app.labs.rafiq.adapters.profiles import StrategyProfile
from app.labs.rafiq.adapters.sizing import SizingPolicy

TIME_BOXED_EXIT = StrategyProfile(
    lane="time_boxed_exit",
    exits=ExitRules(
        take_profit_mult=Decimal("1.20"),      # +20% — reachable inside a short window
        stop_mult=Decimal("0.90"),             # -10% hard stop, tighter than Strategy A
        trailing_frac=None,                    # no trail: the time box IS the exit discipline
        max_hold=timedelta(hours=2),           # the defining rule. Nothing outlives this.
    ),
    sizing=SizingPolicy(
        risk_per_trade=Decimal("0.005"),
        max_pool_fraction=Decimal("0.015"),
        max_impact_pct=Decimal("0.75"),
        exit_stress_factor=Decimal("0.30"),
        max_notional_usd=Decimal(25),
    ),
    sim=SimConfig(decision_latency=timedelta(seconds=10),
                  blackout_threshold=timedelta(minutes=3),
                  liquidity_collapse_frac=Decimal("0.20")),
    entry_threshold=Decimal(68),
    designed_breakeven_win_rate=Decimal("42.9"),  # (10+0.9)/(20+10+0.9), informational
)


def max_capital_days_at_risk(open_positions: int,
                             profile: StrategyProfile = TIME_BOXED_EXIT) -> Decimal:
    """Upper bound on how long capital can be tied up per position, in days —
    the number Karthik's 18-day zombie positions would have been measured
    against, had this rule existed."""
    hours = Decimal(str(profile.exits.max_hold.total_seconds() / 3600))
    return hours / 24
