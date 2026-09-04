"""The PumpFun Lab's frozen rule: copy ONE wallet, sized to our own book.

There is no feature filter here. The entry condition is a fact about somebody
else — the leader bought — and the exit condition is the same fact inverted.
That makes this the first registry on the platform whose rule cannot be
evaluated from a token's own data, and the reason it needs its own opening
logic rather than the Lab's checkpoint machinery.

## The leader, and what measuring him actually showed

`gr3gor14n` (J23qr98…597wsA), #1 on pump.fun's 1-month leaderboard. Measured
directly on chain over 30 days rather than taken from the leaderboard:

    958 swaps across 252 tokens, +453.8 SOL realized
    67 winning tokens / 75 losing tokens
    top-1 token  = 103.1% of all profit
    top-3 tokens = 142.7% of all profit
    hold time    = 8.5 min median, 43% under five minutes

**One token made more than the entire month.** Everything else lost money in
aggregate. This registry is therefore not "copy a profitable trader" — it is
"find out whether a follower can catch the one token that mattered, arriving
late, at 1/100th of the size". Those are different questions and only the
second one is being asked.

Four of the five leaderboard names could not be measured at all: their profile
wallets showed negative or near-zero realized SOL against seven-figure claims,
most likely because the leaderboard counts unrealized holdings. This is the
only one of the five whose trading is visible on chain.

## Why no backtest

We hold five or more price snapshots for 26 of his 252 tokens — 10.3%. A
backtest over a tenth of a distribution whose whole result is a single token
would be noise wearing a number's clothes. Forward only.

## Sizing is OURS, not his

His median buy is ~$106 and his largest is ~$3,100; the whole wallet here is
$100. Positions are a fixed $20 with at most five open, so the book can be
fully deployed across five of his names at once. We mirror WHICH token and
WHEN, never how much.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from decimal import Decimal as D

from app.lab.spec import Exits, Strategy, rules_json

SPEC_VERSION = "pumpfun-1.0.0"

#: The wallet being mirrored.
LEADER_ADDRESS = "J23qr98GjGJJqKq9CBEnyRhHbmkaVxtTJNNxKu597wsA"
LEADER_LABEL = "gr3gor14n"

STARTING_EQUITY = D("100")
FAILURE_EQUITY_FLOOR = D("50")

#: How far back a newly-seen leader trade may be and still be acted on. He
#: holds a median of 8.5 minutes, so a fill copied from a trade an hour old is
#: not a copy of that trade — it is a fresh position at a price his own buying
#: already moved.
MAX_SIGNAL_AGE_SECONDS = 300

STRATEGIES: tuple[Strategy, ...] = (
    Strategy(
        id="CPY-01",
        name=f"COPY-{LEADER_LABEL.upper()}",
        hypothesis=(
            "Mirroring one profitable on-chain trader's entries and exits, "
            "arriving minutes late and at 1/100th of his size, keeps enough of "
            "his result to be worth doing."
        ),
        # Not a checkpoint rule: entries come from his trades, not from a
        # token reaching an age. Recorded as 0 so the rulebook renders.
        checkpoint_minutes=0,
        entry=(),
        size_usd=D("20"),
        max_concurrent=5,
        max_exposure_usd=D("100"),
        # He is the exit. The clock is only a backstop for a position he never
        # sells — without one, a token he abandons ties up a fifth of the book
        # forever.
        exits=Exits(take_profit=None, time_exit_hours=168),
        evidence="ONE_WALLET_MEASURED_ON_CHAIN_OVER_30_DAYS",
        overfit_risk="HIGH",
    ),
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
         "leader": LEADER_ADDRESS,
         "max_signal_age": MAX_SIGNAL_AGE_SECONDS,
         "strategies": [clean(s) for s in STRATEGIES]},
        sort_keys=True, separators=(",", ":"), default=str,
    )


SPEC_HASH = hashlib.sha256(_canonical().encode()).hexdigest()

assert len(STRATEGIES) == 1, "one leader, one wallet"
assert all(s.exits.take_profit is None for s in STRATEGIES), (
    "the leader's sell is the exit; a price target would pre-empt it"
)
assert all(s.entry == () for s in STRATEGIES), (
    "entries come from his trades, not from a feature filter"
)
assert STRATEGIES[0].size_usd * STRATEGIES[0].max_concurrent <= STARTING_EQUITY

__all__ = ["BY_ID", "FAILURE_EQUITY_FLOOR", "LEADER_ADDRESS", "LEADER_LABEL",
           "MAX_SIGNAL_AGE_SECONDS", "SPEC_HASH", "SPEC_VERSION",
           "STARTING_EQUITY", "STRATEGIES", "rules_json"]
