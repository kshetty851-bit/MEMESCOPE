"""SOCIAL — does a coin people are suddenly talking about go up?

Two $100 wallets, $5 a position, twenty open, banking at +10% and compounding
what it realised. The mechanics are identical to Depth v2; only the entry
differs, and between the two wallets only ONE condition differs.

## Why this is not a twelfth version of the same idea

Eleven experiments varied price, liquidity, volume, wallet flow, take-profit,
position size and holding time. All of those are properties of the MARKET.
This is the first that reads something else: how many people are commenting on
the coin, taken from pump.fun's own listing API.

Whether attention leads price is genuinely unknown here. It has never been
measured, because until now it was never collected.

## No threshold, and that is the point

There is no "buy when velocity exceeds N". A threshold picked today would be
fitted to a few hours of data, which is exactly how the mcap filter came to
look like an 8.51 profit factor before split-half took it to 0.72.

The rule is simply: replies are RISING. Positive velocity, nothing more. Where
the interesting cut lies is a question for the data once there is some, not an
assumption to bake in now.

## It cannot fire before it can measure

Velocity needs two readings of the same coin ten minutes apart, and returns
None until it has them. A wallet whose rule requires it therefore buys nothing
at all until the collector has run twice over the same coin — the lab is
self-gating rather than guessing. Expect an idle first hour; that is correct
behaviour, not a fault.

## The control is half the experiment

`SOC-02` draws from the SAME pool — coins in the social feed we can price —
and differs in one respect: it does not care whether comments are rising. If
the two wallets end level, attention is not a signal, and that is a real
answer. Every no-edge finding on this platform came from a control rather than
a strategy, and the random arm has beaten the designed one three times.

## Known limitation, stated up front

Only about a fifth of the coins the social feed surfaces can be priced by this
platform in real time — 27 of 139 when this was written. So both wallets trade
a SUBSET of what pump.fun shows, and the finding will be about that subset.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from decimal import Decimal as D

from app.lab.spec import Condition, Exits, Strategy, rules_json

SPEC_VERSION = "social-1.0.0"

STARTING_EQUITY = D("100")
CYCLE_TARGET_MULTIPLE = D("1.10")
FAILURE_EQUITY_FLOOR = D("50")

SIZE_USD = D("5")
MAX_CONCURRENT = 20

#: Both wallets: a pump.fun coin that the social collector has actually seen.
#: Holding the POOL identical is what makes the pair a controlled comparison —
#: a control free to buy outside the feed would differ in two ways at once.
_POOL: tuple[Condition, ...] = (
    Condition(feature="is_pumpfun", op="gte", value=D("1"),
              reason="not_a_pumpfun_token"),
    Condition(feature="social_seen", op="gte", value=D("1"),
              reason="not_in_the_social_feed"),
)

#: The whole hypothesis, in one line: comments are going UP.
_RISING = Condition(feature="social_reply_velocity", op="gt", value=D("0"),
                    reason="replies_not_rising")


def _wallet(sid: str, name: str, entry: tuple[Condition, ...],
            hypothesis: str, evidence: str) -> Strategy:
    return Strategy(
        id=sid, name=name, hypothesis=hypothesis,
        checkpoint_minutes=30, entry=entry,
        size_usd=SIZE_USD, max_concurrent=MAX_CONCURRENT,
        max_exposure_usd=STARTING_EQUITY,
        exits=Exits(take_profit=None, time_exit_hours=6),
        evidence=evidence, overfit_risk="UNTESTED",
    )


STRATEGIES: tuple[Strategy, ...] = (
    _wallet("SOC-01", "SOCIAL-RISING", (*_POOL, _RISING),
            "A coin whose comment rate is rising outperforms one from the same "
            "feed whose comment rate is not.",
            "FIRST_NON_MARKET_SIGNAL_TESTED_HERE"),
    _wallet("SOC-02", "SOCIAL-CONTROL", _POOL,
            "Being in the social feed at all is the whole effect, and whether "
            "comments are rising adds nothing.",
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
# THE property: the two wallets differ by exactly one condition.
_a, _b = (set(str(c) for c in s.entry) for s in STRATEGIES)
assert _a - _b == {str(_RISING)} and _b - _a == set(), (
    "the control must differ from the signal in the velocity condition ALONE"
)
assert all(s.size_usd * s.max_concurrent <= STARTING_EQUITY for s in STRATEGIES)

__all__ = ["BY_ID", "CYCLE_TARGET_MULTIPLE", "FAILURE_EQUITY_FLOOR",
           "SPEC_HASH", "SPEC_VERSION", "STARTING_EQUITY", "STRATEGIES",
           "rules_json"]
