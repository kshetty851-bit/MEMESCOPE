"""The Graduation Hold Lab — buy the graduation cohort, sell at five minutes.

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

## Why fifty small bets and not ten larger ones

Every loss in this population is TOTAL: the coin dies and the whole stake goes.
Against that, the only lever a book has is how much rides on each bet. A sweep
of 48 shape/exit combinations over 465 corrected graduations, judged on the
figure that matters — the book with its single best trade removed:

    $25 x 4     $1.68
    $10 x 10   $86.18
    $5  x 20   $81.01
    $2  x 50   $93.57      <- least-bad, and this lab's shape

None of them is profitable. That is the finding, and it is why the size was
cut rather than the strategy declared good.

## Why the fifteen-minute arm is gone

Same 465 graduations. The medians of the two horizons are nearly identical —
1.0308 at five minutes against 1.0282 at fifteen — but the share going to zero
TRIPLES, 4.3% to 14.6%. Forty-nine coins alive at five minutes were dead by
fifteen, and 46.5% were simply worse. The extra ten minutes bought almost no
upside and a great deal of ruin.

What that costs, said plainly: this lab no longer carries its own control. A
paired second arm was what distinguished "the horizon is bad" from "the market
was bad this week", and a single arm cannot make that distinction. The 5-vs-15
question is settled on 465 coins of mark data; nothing else is.

## The honest prior

The five-minute figure that started this rests on ONE coin of 138 doing 47.97x
— remove it and +$504.73 becomes +$35.12, median trade 1.037x. The page's own
+$566 headline turned out to be a corrupt denominator, not a return. This runs
as REFUTATION: what is new is the population is right, the baseline is checked,
and the stake is small enough that no single death decides the book.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from decimal import Decimal as D

from app.lab.spec import Condition, Exits, Strategy, rules_json

SPEC_VERSION = "fivemin-5.0.0"

#: Draw candidates from the pump.fun graduation cohort, not from radar.
#: Read by `LabService._due_candidates`; absent means radar, so no other
#: registry changed behaviour when this was added.
CANDIDATE_SOURCE = "graduations"

#: The book each arm starts with.
STARTING_EQUITY = D("100")

#: Below this an arm stops opening.
FAILURE_EQUITY_FLOOR = D("50")

#: THE TWO BOOK SHAPES UNDER TEST — (stake, concurrent), each filling $100.
#:
#: This is the whole experiment now. Both arms take the SAME entry at the SAME
#: instant on the SAME stream and sell on the SAME clock; the only thing that
#: differs is how the hundred dollars is divided. Every loss in this population
#: is TOTAL, so bet size is the one lever a book has, and a sweep over 465
#: graduations put $2 x 50 ahead of $20 x 5 by a distance on the figure that
#: matters — the book with its single best trade removed ($93.57 against $12.41).
#:
#: That was replay. This runs it forward, paired, which is the only way to find
#: out whether the ordering survives real fills — and it restores the control
#: the single-arm version gave up.
BOOK_SHAPES: tuple[tuple[D, int], ...] = ((D("2"), 50), (D("20"), 5))

#: The first shape's stake, kept for the API and page that already read it.
#:
#: $2 x 50 rather than $10 x 10 on the operator's instruction, after a sweep of
#: 48 book-shape/exit combinations over 465 corrected graduations. Losses here
#: are TOTAL — a coin dies and the whole stake goes — so the only lever that
#: improved the record was cutting the size of each bet. Removing the single
#: best trade, $25x4 finished at $1.68, $10x10 at $86.18 and $2x50 at $93.57:
#: still a loss, but the least-bad by a distance.
STAKE_USD = D("2")

#: Minutes after graduation at which a coin is judged. See the module docstring:
#: 2 is the earliest point at which most of the cohort can be PRICED at all.
CHECKPOINT_MINUTES = 2

#: The hold, in minutes, measured from the checkpoint. Shared by both arms.
#:
#: The fifteen-minute arm is retired. On the same 465 graduations the medians
#: were nearly identical (1.0308 against 1.0282) while the share going to zero
#: TRIPLED, 4.3% to 14.6% — 49 coins alive at five minutes were dead by
#: fifteen. The extra ten minutes bought almost no upside and a great deal of
#: ruin, so it is not a horizon worth another book.
HOLD_MINUTES = (5,)

#: Execution fidelity, not a signal. Below this, 7-8% of sells cannot route.
LIQUIDITY_FLOOR = D("100000")

#: THE STAKE NEVER SCALES.
SIZING_SCALES = False

#: NO WALLET RATCHET.
CYCLE_ENABLED = False

#: Liquidity alone: the study bought every graduate, and the two flow features
#: FLOW uses do not exist two minutes after graduation. Kept as a module-level
#: tuple so a second arm can be added later sharing it BY IDENTITY, which is
#: what kept the retired pairing honest.
_EXECUTABLE = (
    Condition(feature="liq", op="gte", value=LIQUIDITY_FLOOR,
              reason="liq_below_100k"),
)


def _arm(stake: D, slots: int) -> Strategy:
    """One wallet. The book SHAPE is the only argument, which is the design."""
    minutes = HOLD_MINUTES[0]
    return Strategy(
        id=f"GRAD-S{int(stake)}",
        name=f"GRAD ${int(stake)} x {slots}",
        hypothesis=(
            f"Buying pump.fun graduations two minutes after they complete and "
            f"selling {minutes} minutes later returns more than it costs."
        ),
        checkpoint_minutes=CHECKPOINT_MINUTES,
        entry=_EXECUTABLE,
        size_usd=stake,
        max_concurrent=slots,
        max_exposure_usd=stake * slots,
        # The clock is the ONLY exit, because the clock is the variable. A
        # take-profit or a stop would decide some trades before the horizon
        # did, and those trades would measure that rule instead.
        exits=Exits(take_profit=None, time_exit_hours=minutes / 60),
        evidence="ONE_47x_COIN_IN_A_GRADUATION_COHORT_OF_138",
        overfit_risk="HIGH",
    )


STRATEGIES: tuple[Strategy, ...] = tuple(_arm(k, n) for k, n in BOOK_SHAPES)

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
assert len(STRATEGIES) == 2, "two arms: one per book shape"
assert len({s.exits.time_exit_hours for s in STRATEGIES}) == 1, (
    "both arms must sell on the SAME clock, or the comparison is not about size"
)
assert len({s.size_usd for s in STRATEGIES}) == 2, (
    "the arms must differ in stake, or there is nothing to compare"
)
assert all(s.entry is _EXECUTABLE for s in STRATEGIES), (
    "the entry is shared BY IDENTITY, so a second arm cannot drift from it"
)
assert all(s.checkpoint_minutes == CHECKPOINT_MINUTES for s in STRATEGIES), (
    "every arm must enter at the same instant or arms are not comparable"
)
assert all(s.exits.take_profit is None and s.exits.stop_loss is None
           for s in STRATEGIES), (
    "the clock is the only exit; a second one would measure itself"
)
assert all(s.size_usd * s.max_concurrent == s.max_exposure_usd
           for s in STRATEGIES), (
    "the concurrent trades must fill the book exactly"
)
assert all(s.max_exposure_usd == STARTING_EQUITY for s in STRATEGIES), (
    "the book is fully deployable, or the stake sizing is not what it claims"
)
assert SIZING_SCALES is False and CYCLE_ENABLED is False, (
    "flat stake, no ratchet — both by instruction"
)

__all__ = ["BY_ID", "CANDIDATE_SOURCE", "CHECKPOINT_MINUTES", "CYCLE_ENABLED",
           "FAILURE_EQUITY_FLOOR", "HOLD_MINUTES", "LIQUIDITY_FLOOR",
           "SIZING_SCALES", "SPEC_HASH", "SPEC_VERSION", "STAKE_USD",
           "STARTING_EQUITY", "STRATEGIES", "rules_json"]
