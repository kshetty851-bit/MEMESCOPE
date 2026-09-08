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

## 1.1.0 — the coverage fix, and why it needed a new version

v1.0.0 copied 7 of 102 of his trades. Almost none of that was the strategy
failing: the scanner subscribes to pump.fun's bonding curve, he trades wherever
he likes, and a mint with no `discovered_tokens` row has no enrichment state,
no snapshots and therefore no price — so the buy was refused `unpriceable` and
every later sell of the same name was refused `not_held`. One gap in our own
coverage cost two ledger rows. We were measuring how much of his universe we
happened to be watching, not whether copying him works.

1.1.0 registers the mint and quotes it on demand at signal time, through the
ordinary enrichment path. **That is a change of regime, not of rule** — the
entry condition is still "he bought" — but it changes which signals are
actionable, so it starts its own tournament rather than contaminating the
first. v1.0.0's book stays on record as the coverage-limited control.

What it does NOT fix: a mint with no indexed pool anywhere still cannot be
priced, and the enrolment adds a provider round trip to the first fill on a new
name. Both are recorded rather than assumed away — `priced_on_demand` on the
decision says whether a fill existed only because of this.

## The refusals are split, because they were three different answers

v1.0.0 wrote `unpriceable` for every entry it declined, which made the coverage
panel unreadable: it could not tell "this coin has no market" from "our data
provider was down". They now separate.

    no_market           the provider answered — this mint has no indexed pool
    quote_unavailable   the provider errored or was never asked
    unpriceable         a print exists but may not be acted on
    enrol_failed        we could not register the mint at all

`no_market` is the one that decides the experiment. He holds a median of 8.5
minutes and freshly launched mints are routinely unindexed for their first
minutes, so if that bucket stays large the finding is that his trades are too
fresh to price at all — copying him is structurally impossible rather than
merely uninstrumented. `quote_unavailable` says nothing about him whatsoever
and must never be read as though it did.

## Sizing is OURS, not his — but the SHAPE of it is his

His median buy is ~$106 and his largest is ~$3,100; the whole wallet here is
$100. We mirror WHICH token and WHEN, never how many dollars.

What we can mirror is his TRANCHES. 958 swaps across 252 tokens is 3.8 swaps a
name — roughly 1.9 buys and 1.9 sells each — so he scales in and scales out,
and the number of times he buys a name is a conviction signal that is fully
visible on chain. His dollar size is not: `leader_sol` is optional because most
of his swaps settle their SOL leg somewhere we cannot attribute, which kills
proportional sizing at the data layer.

So the book is TEN UNITS OF $10, and each of his trades moves one unit:

    he buys a name we do not hold    ->  open one unit
    he buys a name we hold           ->  add one unit, up to four
    he sells a name we hold          ->  sell one unit's worth
    he sells our last unit           ->  close

v1.1.0 refused his second buy as `already_held` and sold the WHOLE position on
his first sell. On a typical name he did buy, buy, sell, sell and we did buy,
refuse, sell everything, nothing — ending at half his size and out while he was
still holding half. Both halves of that asymmetry are gone.

Concurrency is not the binding constraint and never was: 252 entries over 30
days is 0.35 an hour, which against even a two-hour mean hold puts his average
open book below one name. Ten units exist to express DEPTH in a few names, not
breadth across many.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from decimal import Decimal as D

from app.lab.spec import Exits, Strategy, rules_json

SPEC_VERSION = "pumpfun-1.2.0"

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

#: The most units one name may hold. He averages 1.9 buys a token, so four
#: lets nearly every scale-in through while stopping a single coin from eating
#: the book — $40 of $100 is already a large bet on one memecoin.
MAX_UNITS_PER_MINT = 4

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
        # One UNIT, not one position. Ten of them make the book, and a name
        # may hold up to MAX_UNITS_PER_MINT of them.
        size_usd=D("10"),
        max_concurrent=10,
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
         "max_units_per_mint": MAX_UNITS_PER_MINT,
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
assert 1 <= MAX_UNITS_PER_MINT <= STRATEGIES[0].max_concurrent, (
    "a name cannot hold more units than the book has"
)

__all__ = ["BY_ID", "FAILURE_EQUITY_FLOOR", "LEADER_ADDRESS", "LEADER_LABEL",
           "MAX_SIGNAL_AGE_SECONDS", "MAX_UNITS_PER_MINT", "SPEC_HASH",
           "SPEC_VERSION", "STARTING_EQUITY", "STRATEGIES", "rules_json"]
