"""MOVERS — does high turnover mark a coin BEFORE it runs?

Two $100 wallets, $10 a position, ten open. Identical in every respect except
one condition: MOV-01 requires turnover above a floor, MOV-02 does not.

## Where the rule came from

Asked on 2026-09-09 how to track pump.fun's "Movers" before they move. Their
API cannot answer it — `/coins` accepts five sorts and none of them is volume,
price change or trending — so the list has to be rebuilt from our own
observations, and the question became whether movers are distinguishable in
advance at all.

Measured over 4,130 tokens across three days, features read from the five
minutes BEFORE the outcome window and the outcome read only after it:

    tokens that later doubled       turnover 0.63, liquidity $109k
    tokens that did not             turnover 0.11, liquidity $218k

The movers traded roughly 2.8x the volume on HALF the liquidity. Neither term
separates them alone; the ratio does.

## It is a FLOOR, not a score, and the deciles say so

    turnover < 0.005   10-24% doubled
    turnover > 0.02    30-47% doubled, flat and NON-MONOTONIC

The ninth decile (29.7%) did worse than the fourth (41.2%). So turnover tells
you which coins are alive, not which live one will run. Sizing by it, or
ranking on it, would be reading a gradient that is not there. `TURNOVER_FLOOR`
sits at 1.0 — well inside the region that hit 40%, and far enough above the
0.02 cliff that a drifting denominator cannot quietly reintroduce the dead.

## What "doubled" does NOT mean

It means the price TOUCHED 2x at some later observation. It does not mean a
seller got it. Every payoff study here has found peaks are not realisable and
every exit level tested came out negative, so the 40% above is an upper bound
on opportunity and nothing like an expected return. This wallet exists to find
out what a rule can actually keep.

## The rules, and why each is what it is

* **$10 x 10, flat.** Never scales with the balance. When size follows equity
  the result confounds the entry rule with the sizing rule, and V6 could not
  separate them afterwards.
* **Liquidity >= $100k.** Measured from 142,479 Jupiter quotes, a round trip
  costs ~0.78% at that depth and is untradeable below $25k. Note this cuts
  against the signal: movers had LOWER median liquidity, so the floor is
  deliberately giving up part of the population to keep fills honest.
* **No take-profit.** A +10% cap destroyed 93% of gross return in the 15-minute
  study — capping the winners while taking losses in full is backwards. The
  time exit is the only exit, which keeps this a clean test of the ENTRY.
* **No stop loss.** Stops on these fill at ~$0.03. A stop that cannot fill is
  not risk control, it is a comforting line in a config file.
* **30-minute hold.** Median time from a fillable entry to a 2x was 19.7
  minutes (p25 8.1, p75 64.8). Thirty covers the median mover without holding
  into the decay that took the 60-minute graduation cohort to -33%.

## The control is the experiment

MOV-02 draws from the SAME pool at the SAME size with the SAME exit and does
not look at turnover. If the two end level, turnover is not a signal, and that
is a real answer. Every no-edge finding on this platform came from a control
rather than a strategy, and the random arm has now beaten the designed one
several times. Expect that.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from decimal import Decimal as D

from app.lab.spec import Condition, Exits, Strategy, rules_json

SPEC_VERSION = "movers-1.0.0"

STARTING_EQUITY = D("100")
CYCLE_TARGET_MULTIPLE = D("1.10")
FAILURE_EQUITY_FLOOR = D("50")

SIZE_USD = D("10")
MAX_CONCURRENT = 10

#: Hold, in hours. 30 minutes — see the docstring.
TIME_EXIT_HOURS = 0.5

#: The floor the whole hypothesis rests on. Above the measured cliff by a wide
#: margin, because the cliff is where the dead coins stop, not where the
#: movers start.
TURNOVER_FLOOR = D("1.0")

#: Depth at which a round trip is ~0.78% rather than a guess.
MIN_LIQUIDITY_USD = D("100000")

#: BOTH wallets. Holding the pool identical is what makes this a controlled
#: comparison — a control free to buy shallower coins would differ in two ways
#: at once and the result would be unattributable.
_POOL: tuple[Condition, ...] = (
    Condition(feature="is_pumpfun", op="gte", value=D("1"),
              reason="not_a_pumpfun_token"),
    Condition(feature="liq", op="gte", value=MIN_LIQUIDITY_USD,
              reason="too_thin_to_fill_honestly"),
)

# NO ROUTE CONDITION, and that was a correction rather than an omission.
#
# Both arms originally required a two-sided Jupiter quote, on the reasoning
# that a position which cannot be sold is not a trade. Measured before
# shipping: of 60,204 tokens seen in two days, 2,150 have a quote at all —
# 3.6% — and the median first quote arrives 24.2 minutes after first sight.
# The rule would therefore have traded a thirtieth of the pool, and only from
# a point at which the median mover has already run.
#
# The liquidity floor carries that safety instead, and does it on evidence:
# across 142,479 quotes, sells at $100k-250k failed to route 0.5% of the time
# and above $250k not at all. Depth is the execution guarantee here; the quote
# was a redundant gate that happened to be crippling.

#: The whole hypothesis, in one line.
_TURNOVER = Condition(feature="turnover_5m", op="gte", value=TURNOVER_FLOOR,
                      reason="turnover_below_floor")


def _wallet(sid: str, name: str, entry: tuple[Condition, ...],
            hypothesis: str, evidence: str) -> Strategy:
    return Strategy(
        id=sid, name=name, hypothesis=hypothesis,
        # Ten minutes, because that is where the measurement was taken. The
        # research read turnover at each token's TENTH print, and the median
        # token reaches its tenth print 9.8 minutes after first sight (p90
        # 12.4). A five-minute checkpoint would read a different quantity from
        # the one that was validated and call it the same rule.
        checkpoint_minutes=10,
        entry=entry,
        size_usd=SIZE_USD, max_concurrent=MAX_CONCURRENT,
        max_exposure_usd=STARTING_EQUITY,
        exits=Exits(take_profit=None, time_exit_hours=TIME_EXIT_HOURS),
        evidence=evidence, overfit_risk="UNTESTED",
    )


STRATEGIES: tuple[Strategy, ...] = (
    _wallet("MOV-01", "MOVERS-TURNOVER", (*_POOL, _TURNOVER),
            "A coin trading heavily against its own liquidity goes on to "
            "outrun one from the same pool that is not.",
            "PRE_MOVE_SEPARATION_0.63_VS_0.11_MEASURED_2026_09_09"),
    _wallet("MOV-02", "MOVERS-CONTROL", _POOL,
            "Depth and a working route are the whole effect, and turnover "
            "adds nothing.",
            "CONTROL"),
)

BY_ID = {s.id: s for s in STRATEGIES}


def _canonical() -> str:
    def clean(s: Strategy) -> dict:
        d = asdict(s)
        for k in ("hist", "note", "caveats", "hypothesis", "name",
                  "evidence", "overfit_risk", "hist_is_proxy"):
            d.pop(k, None)
        return d

    return json.dumps(
        {"version": SPEC_VERSION,
         "starting_equity": str(STARTING_EQUITY),
         "failure_floor": str(FAILURE_EQUITY_FLOOR),
         "cycle_target": str(CYCLE_TARGET_MULTIPLE),
         "strategies": [clean(s) for s in STRATEGIES]},
        sort_keys=True, separators=(",", ":"), default=str,
    )


SPEC_HASH = hashlib.sha256(_canonical().encode()).hexdigest()

assert len(STRATEGIES) == 2, "the signal and its control"
assert sum(1 for s in STRATEGIES if s.evidence == "CONTROL") == 1
# THE property: the two wallets differ by exactly one condition. Asserted at
# import, because a comparison that quietly differs in two ways answers a
# question nobody asked.
_a, _b = (set(str(c) for c in s.entry) for s in STRATEGIES)
assert _a - _b == {str(_TURNOVER)} and _b - _a == set(), (
    "the control must differ from the signal in the turnover condition ALONE"
)
assert all(s.exits.take_profit is None for s in STRATEGIES), (
    "a take-profit would measure the exit rather than the entry"
)
assert all(s.exits.time_exit_hours == TIME_EXIT_HOURS for s in STRATEGIES)
assert all(s.size_usd * s.max_concurrent <= STARTING_EQUITY for s in STRATEGIES)

__all__ = ["BY_ID", "CYCLE_TARGET_MULTIPLE", "FAILURE_EQUITY_FLOOR",
           "MIN_LIQUIDITY_USD", "SPEC_HASH", "SPEC_VERSION", "STARTING_EQUITY",
           "STRATEGIES", "TIME_EXIT_HOURS", "TURNOVER_FLOOR", "rules_json"]
