"""The Compound Lab's frozen rule — a wallet-level ratchet, not a trade one.

Every tournament so far took profit on a POSITION. This one takes it on the
WALLET: trade the rule until total equity is up 10%, then close everything,
bank the result, and start again from whatever was actually realised. The
question it asks is different from V7's, and worth asking on its own — a
strategy whose individual trades are unremarkable can still ratchet if its
wallet spends enough time above water.

## Why a separate registry rather than another V7 arm

`app.lab.spec.SPEC_HASH` is taken over the whole strategy list AND the fields
of the dataclass, so adding either a strategy or a field changes the hash and
halts the running tournament with `spec_hash_drift`. V7 is mid-flight and
answering a question nobody else has answered. So this gets its own version,
its own hash, and its own tournament row, and shares only the engine.

## The entry rule, and why this one

FLOW: liquidity at or above $300k, liquidity not shrinking over the last 15
minutes, and sell share at or below 45%. It is the only family in V7 sitting
above the cash control, and it descends from the V6-07 loss anatomy, where
every loss was a `dead_zero` and four flow features separated the deaths from
the survivors.

**It is chosen on a handful of trades and that is not evidence.** V7's FLOW
arms had five to seven closed trades each when this was written; V6-07 looked
like a 3.0 profit factor on twenty-three and ended at -25%. This registry is a
hypothesis to be measured, exactly like every one before it.

## No take-profit, on purpose

The wallet target IS the exit. A per-position target would fight it — the
position would be cut at 1.25x while the wallet was still short of its 10%,
and the arm would end up measuring the position rule rather than the ratchet.
Positions are still bounded by the six-hour time exit, so nothing can be held
forever waiting for a wallet target that never arrives.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from decimal import Decimal as D

from app.lab.spec import Condition, Exits, Strategy, rules_json

SPEC_VERSION = "compound-1.0.0"

#: The book the wallet starts with, and the base of the first cycle.
STARTING_EQUITY = D("100")

#: Each cycle ends when equity reaches this multiple of the cycle's base.
#: 10% of the base, compounding: 100 -> 110 -> 121 -> 133.10 -> ...
CYCLE_TARGET_MULTIPLE = D("1.10")

#: Below this the wallet stops opening. Same role as V6's $80 floor: a wallet
#: that has lost half its book is not producing evidence any more, it is
#: producing noise, and it should stop rather than grind to zero unattended.
FAILURE_EQUITY_FLOOR = D("50")

#: The FLOW filter, verbatim from V7's leading family.
_FLOW = (
    Condition(feature="liq", op="gte", value=D("300000"),
              reason="liq_below_300k"),
    Condition(feature="liqchg_15m", op="gte", value=D("0.0"),
              reason="liquidity_not_growing"),
    Condition(feature="sell_share_15m", op="lte", value=D("0.45"),
              reason="sell_share_above_0_45"),
)

STRATEGIES: tuple[Strategy, ...] = (
    Strategy(
        id="CMP-01",
        name="COMPOUND-FLOW",
        hypothesis=(
            "Trading the FLOW filter and taking profit on the WALLET at +10% "
            "compounds, where taking it on each position did not."
        ),
        checkpoint_minutes=30,
        entry=_FLOW,
        size_usd=D("5"),
        max_concurrent=10,
        max_exposure_usd=D("50"),
        # No take-profit: the wallet target is the exit. Still bounded by time.
        exits=Exits(take_profit=None, time_exit_hours=6),
        evidence="V7_LEADING_FAMILY_ON_A_SMALL_SAMPLE",
        overfit_risk="HIGH",
    ),
)

BY_ID = {s.id: s for s in STRATEGIES}


def _canonical() -> str:
    """Canonical JSON of this registry. Mirrors the Lab's, deliberately.

    Prose is excluded for the same reason it is there: a typo fixed in a
    hypothesis must not invalidate a live record.
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
         "strategies": [clean(s) for s in STRATEGIES]},
        sort_keys=True, separators=(",", ":"), default=str,
    )


SPEC_HASH = hashlib.sha256(_canonical().encode()).hexdigest()

assert len(STRATEGIES) == 1, "the Compound Lab is one wallet"
assert all(s.exits.take_profit is None for s in STRATEGIES), (
    "a position target would fight the wallet target"
)
assert all(s.exits.time_exit_hours for s in STRATEGIES), (
    "a position with no target and no clock never returns its capital"
)

__all__ = ["BY_ID", "CYCLE_TARGET_MULTIPLE", "FAILURE_EQUITY_FLOOR",
           "SPEC_HASH", "SPEC_VERSION", "STARTING_EQUITY", "STRATEGIES",
           "rules_json"]
