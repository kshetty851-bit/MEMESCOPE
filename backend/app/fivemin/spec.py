"""The Hold-Horizon Lab — one entry, two clocks, a flat stake, no ratchet.

## The question, and why two strategies rather than two labs

Everything about a trade is held fixed except how long it is held. Both wallets
take the SAME entry object at the SAME checkpoint, stake the SAME $10, and
carry the SAME $100 book. One sells at five minutes, the other at fifteen.

They therefore open the same token at the same instant, and every difference in
their records is the clock — not the entry, not the size, not the venue, not
luck about which tokens each happened to see. That pairing is the whole point,
and it is why these are two strategies inside one registry rather than two
separate labs: two labs would drift apart the moment either was edited.

## The rule set, as the operator stated it

    $100 book, ten trades of $10 each, sell at the horizon,
    then retrade the remaining balance — still $10 a trade.

So: `size_usd = 10`, `max_concurrent = 10`, `max_exposure_usd = 100`. The book
is fully deployed when all ten are open, and capital returns to cash at the
horizon and goes back out at the same flat $10 whatever the wallet is worth.

## What was REMOVED from v1, deliberately

`CYCLE_ENABLED = False`. v1 inherited CMP-01's +10% wallet ratchet: at $110 it
sold the book, banked, and restarted from a new base. That is gone on the
operator's instruction — the wallet now simply trades, and its balance drifts
where the trades take it.

This also removes a confound. A ratchet is itself a return-shaping rule: it
takes profit at a fixed threshold while leaving losses uncapped, so a result
under it measures the hold AND the banking rule together. With it gone, the
record measures the horizon and nothing else.

## The honest prior: FIFTEEN MINUTES HAS ALREADY MEASURED NEGATIVE

On 2026-09-08, 1,348 real executed lab positions (liq >= $100k, their own
recorded entry prices) put the fifteen-minute hold at about **-7.7% gross,
-8.5% net** per trade. The 9% that had no price at the horizon were not missing
data — 37 of them later printed a median of -99.99% and 84 went dark. The
five-minute figure that motivated v1 came from a different population entirely
(pump.fun graduations) and rested on ONE coin of 138 doing 47.97x: remove it and
+$504.73 becomes +$35.12, median trade 1.037x.

Both horizons are therefore run as REFUTATION, not as expectation. The useful
outcome of this lab is most likely a second, cleaner negative — measured
forward, on paired entries, which is the one thing the earlier work could not
do. `overfit_risk` is HIGH on both arms and that is not a formality.

## Five and fifteen minutes are expressed in hours on purpose

`Exits.time_exit_hours` is compared against a float `held_hours`, so 5/60 and
15/60 work exactly. It is NOT expressed by adding a minutes field to `Exits`:
that dataclass is shared, `asdict` puts every field into the canonical JSON,
and a new field with a null default would change the hash of V7 and the
Compound Lab and halt both of them mid-flight.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from decimal import Decimal as D

from app.compound import spec as cspec
from app.lab.spec import Exits, Strategy, rules_json

SPEC_VERSION = "fivemin-2.0.0"

#: The book each wallet starts with. Both arms get their own $100.
STARTING_EQUITY = D("100")

#: Below this a wallet stops opening — same role as the $80 floor elsewhere.
FAILURE_EQUITY_FLOOR = D("50")

#: THE STAKE, and it never moves. Ten of these fill the book exactly.
STAKE_USD = D("10")

#: The two horizons under test, in minutes. The only thing that differs.
HOLD_MINUTES = (5, 15)

#: THE STAKE NEVER MOVES. Read by `LabService._open`; absent or True restores
#: the equity-scaled ladder every other tournament uses.
SIZING_SCALES = False

#: NO WALLET RATCHET. Read by `CompoundService`; absent or True restores the
#: bank-at-target cycle that CMP-01 and fivemin-1.0.0 ran.
CYCLE_ENABLED = False

#: THE CONTROL'S OWN ENTRY TUPLE, imported rather than restated.
#:
#: Transcribing it produced two silent differences on the first attempt —
#: `Decimal("0")` against `Decimal("0.0")`, and a different reason string —
#: neither of which changes what the rule ADMITS, both of which change the
#: canonical hash and the refusal label.
#:
#: Taking the object also means BOTH arms below share one entry by identity,
#: not by copy. They cannot drift apart, so the pairing that makes this a
#: controlled comparison cannot be broken by editing one of them.
_FLOW = cspec.STRATEGIES[0].entry


def _arm(minutes: int) -> Strategy:
    """One wallet. The horizon is the only argument, which is the design."""
    return Strategy(
        id=f"HOLD-{minutes:02d}",
        name=f"HOLD-{minutes}M",
        hypothesis=(
            f"Buying on FLOW and selling at {minutes} minutes returns more than "
            f"it costs, with the stake flat and no wallet ratchet."
        ),
        checkpoint_minutes=30,
        entry=_FLOW,
        size_usd=STAKE_USD,
        max_concurrent=10,
        max_exposure_usd=STAKE_USD * 10,
        # No take-profit and no stop: the clock is the ONLY exit, because the
        # clock is the variable. A second exit rule would decide some trades
        # before the horizon did, and those trades would measure that rule.
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
         "starting_equity": str(STARTING_EQUITY),
         "failure_floor": str(FAILURE_EQUITY_FLOOR),
         "cycle_enabled": CYCLE_ENABLED,
         "sizing_scales": SIZING_SCALES,
         "strategies": [clean(s) for s in STRATEGIES]},
        sort_keys=True, separators=(",", ":"), default=str,
    )


SPEC_HASH = hashlib.sha256(_canonical().encode()).hexdigest()

assert len(STRATEGIES) == 2, "two arms: one per horizon"
assert len({s.exits.time_exit_hours for s in STRATEGIES}) == 2, (
    "the two arms must differ in the clock, or there is nothing to compare"
)
assert all(s.entry is _FLOW for s in STRATEGIES), (
    "both arms share ONE entry object; a copy could drift and break the pairing"
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

__all__ = ["BY_ID", "CYCLE_ENABLED", "FAILURE_EQUITY_FLOOR", "HOLD_MINUTES",
           "SIZING_SCALES", "SPEC_HASH", "SPEC_VERSION", "STAKE_USD",
           "STARTING_EQUITY", "STRATEGIES", "rules_json"]
