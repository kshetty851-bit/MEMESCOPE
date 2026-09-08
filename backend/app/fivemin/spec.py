"""The Five-Minute Lab — the wallet ratchet, on a five-minute hold, flat size.

## Why it exists, stated honestly

The graduation study measured what buying every pump.fun graduation and selling
at a fixed age would have returned. The five-minute row read +$504.73 on a $100
book and every longer horizon read worse. That is the observation this registry
was asked to act on.

**It is one coin.** Of 138 trades, the best did 47.97x and produced 59.7% of all
gross profit; the second best did 4.69x and the 5-10x band is empty. Remove that
single trade and +$504.73 becomes +$35.12. The median trade returned 1.037x.

So this is a hypothesis fitted to one outlier, on a population — pump.fun
graduations — that is not even the population this lab trades. It is run
because it is cheap to run and forward evidence is the only thing that settles
it, not because the number that motivated it is good evidence. `overfit_risk`
is HIGH and that is not a formality.

## The two changes from CMP-01, and nothing else

CMP-01 held for six hours and let its stake grow with the wallet. This holds for
five minutes and never changes stake. Everything else — the FLOW entry, the +10%
wallet ratchet, $100 start, $5 base, ten concurrent — is identical, so a
difference between the two is attributable to the two things that differ rather
than to a redesign.

## Flat size, on the operator's instruction

`SIZING_SCALES = False`. The stake is $5 whatever the wallet is worth.

This matters more than it looks. The wallet ratchet already compounds: each
cycle's base is the last cycle's target, so 100 -> 110 -> 121. Letting the
stake ALSO double at 2x equity would run two compounding effects at once, and a
result could not be attributed to either. The Compound spec makes the same
argument for removing the per-position take-profit — that an arm carrying two
exit rules measures the wrong one — and this is that argument applied to size.

## Five minutes is expressed in hours on purpose

`Exits.time_exit_hours` is compared against a float `held_hours`, so 5/60 works
exactly. It is NOT expressed by adding a minutes field to `Exits`: that
dataclass is shared, `asdict` puts every field into the canonical JSON, and a
new field with a null default would change the hash of V7 and the Compound Lab
and halt both of them mid-flight.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from decimal import Decimal as D

from app.compound import spec as cspec
from app.lab.spec import Exits, Strategy, rules_json

SPEC_VERSION = "fivemin-1.0.0"

#: The book the wallet starts with, and the base of the first cycle.
STARTING_EQUITY = D("100")

#: Each cycle ends when equity reaches this multiple of the cycle's base.
CYCLE_TARGET_MULTIPLE = D("1.10")

#: Below this the wallet stops opening — same role as the $80 floor elsewhere.
FAILURE_EQUITY_FLOOR = D("50")

#: The hold, in minutes. The number this lab exists to test.
TIME_EXIT_MINUTES = 5

#: THE STAKE NEVER MOVES. Read by `LabService._open`; absent or True restores
#: the equity-scaled ladder every other tournament uses.
SIZING_SCALES = False

#: THE CONTROL'S OWN ENTRY TUPLE, imported rather than restated.
#:
#: Transcribing it produced two silent differences on the first attempt —
#: `Decimal("0")` against `Decimal("0.0")`, and a different reason string —
#: neither of which changes what the rule ADMITS, both of which change the
#: canonical hash and the refusal label. Two registries that are supposed to
#: differ in exactly two ways would then have differed in four, and the two
#: extra would have been invisible.
#:
#: Taking the object means the comparison stays a comparison: if CMP-01's
#: entry is ever edited, this moves with it, and the experiment keeps asking
#: about the hold and the stake rather than quietly about the entry too.
_FLOW = cspec.STRATEGIES[0].entry

STRATEGIES: tuple[Strategy, ...] = (
    Strategy(
        id="FM-01",
        name="FIVEMIN-FLOW",
        hypothesis=(
            "Holding five minutes and taking profit on the WALLET at +10% "
            "compounds, where holding six hours did not."
        ),
        checkpoint_minutes=30,
        entry=_FLOW,
        size_usd=D("5"),
        max_concurrent=10,
        max_exposure_usd=D("50"),
        # No take-profit: the wallet target is the exit, as in CMP-01. The
        # clock is the only per-position rule, and it is the variable.
        exits=Exits(take_profit=None, time_exit_hours=TIME_EXIT_MINUTES / 60),
        evidence="ONE_47x_COIN_IN_A_GRADUATION_COHORT_OF_138",
        overfit_risk="HIGH",
    ),
)

BY_ID = {s.id: s for s in STRATEGIES}


def _canonical() -> str:
    """The bytes the hash is taken over — the RULES, not the prose.

    Same treatment as every other registry here: renaming a strategy or
    rewriting its hypothesis must not invalidate a live record, and changing
    what it trades must.
    """
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
         "sizing_scales": SIZING_SCALES,
         "strategies": [clean(s) for s in STRATEGIES]},
        sort_keys=True, separators=(",", ":"), default=str,
    )


SPEC_HASH = hashlib.sha256(_canonical().encode()).hexdigest()

assert len(STRATEGIES) == 1, "the Five-Minute Lab is one wallet"
assert all(s.exits.take_profit is None for s in STRATEGIES), (
    "a position target would fight the wallet target"
)
assert all(s.exits.time_exit_hours for s in STRATEGIES), (
    "a position with no target and no clock never returns its capital"
)
assert SIZING_SCALES is False, (
    "the stake is flat by instruction; scaling it would run two compounding "
    "effects at once and make the result unattributable"
)

__all__ = ["BY_ID", "CYCLE_TARGET_MULTIPLE", "FAILURE_EQUITY_FLOOR",
           "SIZING_SCALES", "SPEC_HASH", "SPEC_VERSION", "STARTING_EQUITY",
           "STRATEGIES", "TIME_EXIT_MINUTES", "rules_json"]
