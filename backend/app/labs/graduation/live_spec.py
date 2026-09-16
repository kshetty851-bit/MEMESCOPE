"""The graduation arm the real wallet is allowed to know about.

## Why this is a registry of its own

`RealWalletDriver` buys what a Lab strategy already decided, read from
`lab_decisions` and keyed by a strategy that `app.lab.spec.BY_ID` must know.
The obvious move — add `B3_198k_5m` to that registry — is the wrong one:
`SPEC_HASH` is taken over the whole of `STRATEGIES` and is written onto every
tournament row at activation, so a new entry drifts the hash and `lab_tick`
answers `{"halted": "spec_hash_drift"}` on every pass thereafter. V7 is
currently running against a matching hash. Adding a strategy here would stop
it.

So this follows what `pumpfun`, `compound` and `momentum` already do: its own
`SPEC_VERSION`, its own `SPEC_HASH`, its own tournament row on the shared
tables. Every query that could see it is scoped by `spec_version`,
`tournament_id`, `spec_hash`, or the registry's own ids, so V7 cannot see these
rows and this cannot see V7's.

## Why the id is short and ugly

`lab_decisions.strategy_id` is `String(8)`. `B3_198k_5m` is eleven characters
and would be truncated or rejected, so the live arm carries a short name and
`PAPER_BOOK` records which paper arm it mirrors.

## The five-minute hold

`Exits.time_exit_hours` is annotated `int`, but `evaluate_exit` compares it
against `MarkState.held_hours`, which is a float — the comparison is ordinary
arithmetic and a fractional value works exactly as written. It is expressed
this way rather than by adding a `time_exit_minutes` field because `Exits` is
expanded by `asdict` into V7's canonical JSON: a new field, even defaulting to
None, changes V7's hash and halts it. Reusing the existing field keeps
`exit_driver`'s one implementation of "when do we sell" intact, which is the
property it was built for.

Pure data and pure functions. No I/O, no clock, no settings.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from decimal import Decimal
from typing import TypeVar

from app.lab.spec import Exits, Strategy

D = Decimal
_Money = TypeVar("_Money", float, Decimal)

SPEC_VERSION = "gradlive-1.0.0"

#: The paper arm this mirrors. Recorded so a reader can put the real book
#: beside the arm it is supposed to be copying, and so nothing has to infer
#: the mapping from a truncated id.
PAPER_BOOK = "B3_198k_5m"

#: The pool floor the paper arm buys above. Not enforced here — the graduation
#: recorder's own entry rule decides, and this registry only mirrors what it
#: chose — but stated because it is the single most load-bearing number in the
#: strategy: measured over 2,087 graduations, tokens above it collapse >80%
#: within five minutes at 0.47% against 13.85% for the whole population.
POOL_FLOOR_USD = 198_000

#: Five minutes, as hours, because that is the unit the shared exit rule reads.
#:
#: A float, not a Decimal, and the difference is 6 seconds of a 28-second
#: margin. `exit_driver` computes `held_hours` as `total_seconds() / 3600`, so
#: at exactly five minutes it holds the float 300/3600. Decimal(5)/Decimal(60)
#: carries more digits than that float and is fractionally LARGER, so
#: `held >= exit` stayed false at 5m00s and the position left on the next pass
#: instead. Computing the bound the same way the mark does makes the
#: comparison exact at the boundary.
HOLD_MINUTES = 5
HOLD_HOURS = HOLD_MINUTES / 60

#: How stale a decision may be when the wallet acts on it.
#:
#: The shared driver default is ten minutes, which is wrong here by an order of
#: magnitude. The hold is five minutes and the earliest collapse observed in
#: this arm's own 145 trades landed at 5m28s, so a decision acted on nine
#: minutes late buys a token at the edge of the cliff the strategy exists to
#: stay in front of. Sixty seconds is one driver tick.
MAX_DECISION_AGE_SECONDS = 60

STARTING_EQUITY = D("1000")
FAILURE_EQUITY_FLOOR = D("500")

STRATEGIES: tuple[Strategy, ...] = (
    Strategy(
        id="G-B3-5M",
        name="GRADUATION-B3-5MIN",
        hypothesis=(
            "A pump.fun graduation whose pool is already deep enough is worth "
            "holding for exactly five minutes: long enough to collect the "
            "post-graduation drift, short enough to be gone before the "
            "collapses start."
        ),
        # Entries come from the graduation recorder's own band rule at the
        # moment a pool opens, not from a token reaching an age. Recorded as 0
        # so the rulebook renders.
        checkpoint_minutes=0,
        entry=(),
        size_usd=D("100"),
        # Six was the most the paper arm ever held at once over 29 hours, so
        # ten is headroom rather than a target. Below about $56 a position the
        # flat priority fee exceeds the arm's whole gross move, which is why
        # the ticket is $100 and not a tenth of the book.
        max_concurrent=10,
        max_exposure_usd=D("1000"),
        # The clock IS the strategy. No take-profit: replaying 58 exit rules
        # over the arm's own trades, the best changed one trade of 136. No
        # stop: the feed refreshes every 43s, so a -10% stop touched two trades
        # and made both worse (-19.7% to -23.3%, -28.5% to -30.0%).
        exits=Exits(take_profit=None, stop_loss=None, time_exit_hours=HOLD_HOURS),
        evidence="FORWARD_PAPER_145_TRADES_OVER_29_HOURS",
        overfit_risk="HIGH",
        note=(
            "NOT CALLED by the graduation lab's own gate: profit factor 1.39 "
            "against a bar of 2.97, and no baseline arm is running. Measured "
            "expectancy is NEGATIVE once the rug rate is priced in — 0.47% of "
            "qualifying tokens collapse inside five minutes against a "
            "break-even of 0.284%. Registered so it CAN be nominated; "
            "nominating it is a separate decision and starting it is the "
            "operator's alone."
        ),
    ),
)

BY_ID = {s.id: s for s in STRATEGIES}


def fundable(cash: _Money, *, holding: bool, ticket: _Money,
             floor: _Money) -> _Money | None:
    """What the $100 account spends on its next entry, or None to skip it.

    ONE rule for the board and the wallet: `api._funded_walk` walks it over the
    paper trades and `RealWalletDriver` applies it to the live balance, so the
    balance the page prints is the balance the wallet would have.

    * Nothing held: the whole ticket, or all the cash when there is less — but
      never under `floor`, below which the flat priority fee outruns the move.
    * Something held: a WHOLE ticket or nothing. "$200 holds two" means two
      full positions, never a full one and a scrap.

    Floats (the board) and Decimals (the wallet) both work; do not mix them.
    """
    if holding:
        return ticket if cash >= ticket else None
    size = min(ticket, cash)
    return size if size >= floor else None


def _canonical() -> str:
    """Canonical JSON of this registry — the thing the hash is taken over.

    The same exclusions as the V6/V7 registry, for the same reason: a typo
    fixed in prose must not invalidate a live record.
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
         "paper_book": PAPER_BOOK,
         "pool_floor_usd": POOL_FLOOR_USD,
         "max_decision_age_s": MAX_DECISION_AGE_SECONDS,
         "strategies": [clean(s) for s in STRATEGIES]},
        sort_keys=True, separators=(",", ":"), default=str,
    )


SPEC_HASH = hashlib.sha256(_canonical().encode()).hexdigest()

# --- invariants ---------------------------------------------------------------
# Each of these is a property something downstream relies on, asserted here so a
# later edit fails at import rather than in production.

assert len(STRATEGIES) == 1, "one arm mirrors one paper book"
assert all(len(s.id) <= 8 for s in STRATEGIES), (
    "lab_decisions.strategy_id is String(8); a longer id does not round-trip"
)
assert STRATEGIES[0].exits.time_exit_hours == HOLD_HOURS, (
    "the clock is the strategy; without it there is no exit at all"
)
assert STRATEGIES[0].exits.take_profit is None, (
    "58 exit rules were replayed and the best changed one trade of 136"
)
assert STRATEGIES[0].exits.stop_loss is None, (
    "a stop on a 43-second feed fills below its own trigger; measured worse"
)
assert MAX_DECISION_AGE_SECONDS <= 300, (
    "a decision older than the hold buys the token at the cliff, not before it"
)
assert (STRATEGIES[0].size_usd * STRATEGIES[0].max_concurrent
        <= STARTING_EQUITY), "the book cannot fund its own concurrency"

__all__ = ["BY_ID", "FAILURE_EQUITY_FLOOR", "HOLD_HOURS", "HOLD_MINUTES",
           "MAX_DECISION_AGE_SECONDS", "PAPER_BOOK", "POOL_FLOOR_USD",
           "SPEC_HASH", "SPEC_VERSION", "STARTING_EQUITY", "STRATEGIES"]
