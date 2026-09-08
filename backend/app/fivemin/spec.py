"""The Graduation Hold Lab — buy the graduation cohort, sell at 5 or 15 minutes.

## Why this replaces fivemin-2.0.0 after a day

v2 tested the five-minute hold on RADAR's population with a $300,000 liquidity
floor, both inherited from CMP-01 so the two labs would stay comparable. The
operator asked the obvious question — we are trading recently graduated tokens
quickly, so why the liquidity? — and the measurements answered it:

    only 3.6% of the tokens the Compound Lab judged had ever graduated
    the median graduate carries $39,998 of liquidity at 30 minutes
    a $300k floor admits 11% of graduates (23 of 205)

So v2 was testing a hypothesis taken from the graduation study against a set of
coins that study never looked at, behind a floor 7.5x the median graduate.
Comparability with the wrong control is not worth trading the wrong population.

## What this lab buys

`CANDIDATE_SOURCE = "graduations"` draws candidates from `pumpfun_graduations`
rather than radar. That is the cohort the +$504.73 figure came from.

## Why entry is at graduation + 2 minutes

The operator's instruction was to buy within seconds — "or else we will lose
the momentum" — and v3.0.0 shipped with a 5-minute checkpoint that was never
asked for. This is the correction, and 2 rather than 0 for one reason only:
**the lab cannot buy what it cannot price.** `_open` needs a price AND a
liquidity from the market series, and over 362 graduates in two days those
exist for:

    at graduation   23%   (85)
    +1 minute       32%   (117)
    +2 minutes      75%   (271)
    +3 minutes      86%   (311)

Entering at +0 would trade under a quarter of the cohort, and not a random
quarter — the coins already priced at their graduation stamp are the ones
already trading actively. The record would then describe that slice while
appearing to describe graduations.

The momentum this costs was measured rather than assumed. Over 104 graduates
with a genuinely new price print between +1 and +3 minutes, the multiple was:

    p25 0.579   median 1.0006   p75 1.112   p95 2.017

Violently two-sided, and the MEDIAN IS FLAT. There is no systematic run-up in
the first minutes to arrive late for; waiting declines a coin-flip rather than
missing a rally. So 2 minutes buys triple the coverage for no measurable
median cost.

(The graduation replay on `/graduations/paper` does enter at the stamp with
100% coverage, because it prices from `mcap_usd_at_graduation` and never
touches a route. That is exactly why it is a replay: it assumes the fill. This
lab exists to find out whether the fill is real.)

## Why the only entry condition is liquidity

The study bought EVERY graduate; it had no signal. FLOW cannot be the filter
here either way, because `liqchg_15m` and `sell_share_15m` need fifteen minutes
of history that does not exist two minutes after a coin graduates — under FLOW
this lab would refuse nearly everything as `unknown_*`, which is already the
second-largest refusal reason on CMP-01 at 15.1%.

The $100,000 floor is therefore NOT a signal. It is execution fidelity, and it
is set from measured Jupiter routing over 142,479 quotes:

    liquidity      buy impact   sell impact   SELL HAS NO ROUTE
    under $25k        98.96%          -             37.4%
    $25k-$50k          0.66%       0.50%             8.3%
    $50k-$100k         0.78%       0.89%             6.8%
    $100k-$250k        0.61%       0.75%             0.5%

Below $100k the danger is not price impact, it is that 7-8% of sells cannot
route at all. `sell_route_loss` is `hold_and_retry`, so an unroutable position
sails past its horizon and the trade then measures the delay instead of the
clock. On a lab whose entire question is the clock, that is fatal. $100k is the
lowest floor that keeps the exit honest, and it still admits 42% of graduates
(87 of 205) against v2's 11%.

## The pairing, stated honestly

Both arms read one stream and share ONE entry object by identity, so whenever
both have capacity they buy the same coin at the same instant. They are not
guaranteed to take identical trade sets: the five-minute arm returns its
capital three times faster, so under a burst it can take a coin the fifteen
holds no room for. At the measured rate — about 52 graduations an hour, 42%
clearing the floor, so roughly 22 admissions an hour against the fifteen-minute
arm's capacity of 40 — that should be rare rather than routine. Faster
redeployment is a real property of the shorter hold and the operator asked for
it explicitly ("retrade again with the remaining balance"), so it is measured
rather than suppressed.

## The honest prior

Fifteen minutes has already measured about -8.5% net per trade on 1,348 real
positions, and the five-minute figure rests on ONE coin of 138 doing 47.97x —
remove it and +$504.73 becomes +$35.12, median trade 1.037x. Both arms run as
REFUTATION. What is new is that this time the population is the right one.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from decimal import Decimal as D

from app.lab.spec import Condition, Exits, Strategy, rules_json

SPEC_VERSION = "fivemin-3.1.0"

#: Draw candidates from the pump.fun graduation cohort, not from radar.
#: Read by `LabService._due_candidates`; absent means radar, so no other
#: registry changed behaviour when this was added.
CANDIDATE_SOURCE = "graduations"

#: The book each arm starts with.
STARTING_EQUITY = D("100")

#: Below this an arm stops opening.
FAILURE_EQUITY_FLOOR = D("50")

#: THE STAKE, and it never moves. Ten of these fill the book exactly.
STAKE_USD = D("10")

#: Minutes after graduation at which a coin is judged. See the module docstring:
#: 2 is the earliest point at which most of the cohort can be PRICED at all.
CHECKPOINT_MINUTES = 2

#: The two horizons under test, in minutes, measured from the checkpoint.
HOLD_MINUTES = (5, 15)

#: Execution fidelity, not a signal. Below this, 7-8% of sells cannot route.
LIQUIDITY_FLOOR = D("100000")

#: THE STAKE NEVER SCALES.
SIZING_SCALES = False

#: NO WALLET RATCHET.
CYCLE_ENABLED = False

#: ONE object, shared by both arms by identity so they cannot drift apart.
#: Liquidity alone: the study bought every graduate, and the two flow features
#: FLOW uses do not exist five minutes after graduation.
_EXECUTABLE = (
    Condition(feature="liq", op="gte", value=LIQUIDITY_FLOOR,
              reason="liq_below_100k"),
)


def _arm(minutes: int) -> Strategy:
    """One wallet. The horizon is the only argument, which is the design."""
    return Strategy(
        id=f"GRAD-{minutes:02d}",
        name=f"GRAD-{minutes}M",
        hypothesis=(
            f"Buying pump.fun graduations two minutes after they complete and "
            f"selling {minutes} minutes later returns more than it costs."
        ),
        checkpoint_minutes=CHECKPOINT_MINUTES,
        entry=_EXECUTABLE,
        size_usd=STAKE_USD,
        max_concurrent=10,
        max_exposure_usd=STAKE_USD * 10,
        # The clock is the ONLY exit, because the clock is the variable. A
        # take-profit or a stop would decide some trades before the horizon
        # did, and those trades would measure that rule instead.
        exits=Exits(take_profit=None, time_exit_hours=minutes / 60),
        evidence=("FIFTEEN_MIN_MEASURED_-8.5pct_NET_ON_1348_REAL_POSITIONS"
                  if minutes == 15
                  else "ONE_47x_COIN_IN_A_GRADUATION_COHORT_OF_138"),
        overfit_risk="HIGH",
    )


STRATEGIES: tuple[Strategy, ...] = tuple(_arm(m) for m in HOLD_MINUTES)

BY_ID = {s.id: s for s in STRATEGIES}


def _canonical() -> str:
    """The bytes the hash is taken over — the RULES, not the prose."""
    def clean(s: Strategy) -> dict:
        d = asdict(s)
        for k in ("hist", "note", "caveats", "hypothesis", "name",
                  "evidence", "overfit_risk", "hist_is_proxy"):
            d.pop(k, None)
        return d

    return json.dumps(
        {"version": SPEC_VERSION,
         "candidate_source": CANDIDATE_SOURCE,
         "starting_equity": str(STARTING_EQUITY),
         "failure_floor": str(FAILURE_EQUITY_FLOOR),
         "cycle_enabled": CYCLE_ENABLED,
         "sizing_scales": SIZING_SCALES,
         "strategies": [clean(s) for s in STRATEGIES]},
        sort_keys=True, separators=(",", ":"), default=str,
    )


SPEC_HASH = hashlib.sha256(_canonical().encode()).hexdigest()

assert CANDIDATE_SOURCE == "graduations", (
    "this lab exists to trade the graduation cohort; radar is what it replaced"
)
assert len(STRATEGIES) == 2, "two arms: one per horizon"
assert len({s.exits.time_exit_hours for s in STRATEGIES}) == 2, (
    "the two arms must differ in the clock, or there is nothing to compare"
)
assert all(s.entry is _EXECUTABLE for s in STRATEGIES), (
    "both arms share ONE entry object; a copy could drift and break the pairing"
)
assert all(s.checkpoint_minutes == CHECKPOINT_MINUTES for s in STRATEGIES), (
    "both arms must enter at the same instant or they are not comparable"
)
assert all(s.exits.take_profit is None and s.exits.stop_loss is None
           for s in STRATEGIES), (
    "the clock is the only exit; a second one would measure itself"
)
assert all(s.size_usd * s.max_concurrent == s.max_exposure_usd
           for s in STRATEGIES), (
    "ten trades of the stake must fill the book exactly"
)
assert SIZING_SCALES is False and CYCLE_ENABLED is False, (
    "flat stake, no ratchet — both by instruction"
)

__all__ = ["BY_ID", "CANDIDATE_SOURCE", "CHECKPOINT_MINUTES", "CYCLE_ENABLED",
           "FAILURE_EQUITY_FLOOR", "HOLD_MINUTES", "LIQUIDITY_FLOOR",
           "SIZING_SCALES", "SPEC_HASH", "SPEC_VERSION", "STAKE_USD",
           "STARTING_EQUITY", "STRATEGIES", "rules_json"]
