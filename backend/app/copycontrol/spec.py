"""CPY-02 — the control CPY-01 never had.

The PumpFun Lab asks "does copying this trader work?" and, alone among the labs
here, it shipped without anything to answer it against. That is the one omission
this platform cannot afford: **every no-edge finding on it came from a control
rather than from a strategy, and the random arm has beaten the designed one
three times.**

## The question this arm exists to answer

CPY-01 is up on five trades, and two of those produced all of it. There are two
completely different explanations and its own record cannot separate them:

1. the leader picks well and his sell is a good exit, or
2. buying almost any pump.fun token at those moments, for those durations, paid.

Without a control, one confirmed hit and one open lottery ticket look exactly
like an edge. They also look exactly like the eight findings that were not.

## Paired, not merely parallel

Each control position is tied to ONE CPY-01 position and copies everything about
it except the identity of the token:

* **same instant** — it opens when the leader's buy is acted on, not on a
  schedule of its own;
* **same size** — read from the paired CPY-01 position rather than set here, so
  a future change to CPY-01's sizing (1.2.0 tranches $10 x 10 where 1.0.0 used
  $20 x 5) cannot silently make the two arms differ in a second way;
* **same holding period** — it closes when the leader sells HIS token, so
  duration is matched and cannot confound the comparison.

An unpaired random arm on a 168h clock would have differed in entry timing,
size and holding period all at once, and no difference between the two could
have been attributed to anything.

## The choice is random but NOT arbitrary

The token is drawn with a generator seeded from the leader's transaction
signature. That makes every pick reproducible from the ledger — "why that
token?" is answerable months later by replaying the seed — while remaining
independent of anything about the token itself. A control nobody can audit is
not evidence.

## What it cannot tell you

It starts today. CPY-01's first five trades, including the +$55.17 that has
already closed and the position still open, have NO control and never will —
you cannot run a control retroactively. **Read this arm only against trades
opened after its own `valid_from`.**

It also inherits CPY-01's dependence on our coverage: a token we cannot price is
a token neither arm can hold, so both trade the subset this platform can see.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from decimal import Decimal as D

from app.lab.spec import Exits, Strategy, rules_json

#: 16 characters is the hard ceiling — `lab_tournaments.spec_version` and
#: `lab_strategies.version` are both String(16), and "copycontrol-1.0.0" is 17.
#: The database rejected it outright rather than truncating, which is the
#: right failure: a silently truncated spec_version would have made
#: `activate()` unable to find its own tournament on the next tick and opened
#: a second one beside it every minute.
SPEC_VERSION = "cpy02-1.0.0"

STARTING_EQUITY = D("100")

#: Fallback only. The real size is read from the paired CPY-01 position at open
#: time; this is what a pairing with no readable size would use, and a test
#: holds that the fallback never silently becomes the normal path.
FALLBACK_SIZE_USD = D("10")

#: Ceiling on concurrent control positions. Matches CPY-01's 1.2.0 book so the
#: two arms can hit the same wall at the same time.
MAX_CONCURRENT = 10

#: How far back a leader signal may be and still be mirrored. Identical to
#: pumpfun's own, because a control that acts on staler information than the
#: strategy is not a control.
MAX_SIGNAL_AGE_SECONDS = 300

CONTROL = Strategy(
    id="CPY-02",
    name="CONTROL-RANDOM",
    hypothesis=(
        "Buying a random pump.fun token at the moments the leader buys, and "
        "holding it exactly as long as he holds his, does as well as copying "
        "the token he actually chose."
    ),
    checkpoint_minutes=0,
    entry=(),  # the trigger is a paired leader signal, not a feature rule
    size_usd=FALLBACK_SIZE_USD,
    max_concurrent=MAX_CONCURRENT,
    max_exposure_usd=STARTING_EQUITY,
    # Identical to CPY-01. The real exit is the paired close; the 168h clock is
    # the same backstop CPY-01 carries, present so a control position whose
    # pair somehow never closes cannot sit open forever.
    exits=Exits(take_profit=None, time_exit_hours=168,
                sell_route_loss="hold_and_retry"),
    evidence="CONTROL",
    overfit_risk="NONE_IT_CHOOSES_AT_RANDOM",
)

STRATEGIES: tuple[Strategy, ...] = (CONTROL,)
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
         "strategies": [clean(s) for s in STRATEGIES]},
        sort_keys=True, separators=(",", ":"), default=str,
    )


SPEC_HASH = hashlib.sha256(_canonical().encode()).hexdigest()

assert len(STRATEGIES) == 1
assert CONTROL.evidence == "CONTROL"
# It must carry NO entry rule. The instant this arm acquires a condition it
# stops being a control and becomes a second strategy, and CPY-01 loses the
# only thing it can be measured against.
assert CONTROL.entry == (), "a control with a rule is not a control"
# Exits must match CPY-01's, or holding period becomes a second variable.
assert CONTROL.exits.take_profit is None and CONTROL.exits.stop_loss is None
assert CONTROL.exits.time_exit_hours == 168
assert len(SPEC_VERSION) <= 16, "lab_tournaments.spec_version is String(16)"

__all__ = ["BY_ID", "CONTROL", "FALLBACK_SIZE_USD", "MAX_CONCURRENT",
           "MAX_SIGNAL_AGE_SECONDS", "SPEC_HASH", "SPEC_VERSION",
           "STARTING_EQUITY", "STRATEGIES", "rules_json"]
