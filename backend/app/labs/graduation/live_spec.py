"""The graduation arms the real wallet is allowed to know about.

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
and would be truncated or rejected, so each live arm carries a short name and
`PAPER_BOOKS` records which paper arm it mirrors.

## The hold

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

#: 1.4.0 adds G-QUIET (2026-09-21); 1.5.0 adds its four-minute twin
#: G-QUIET4 (2026-09-22). The version MUST be bumped with a new
#: strategy: `strategy_row_id` finds the tournament row by version, so adding
#: one under the old version leaves that row holding the old `SPEC_HASH`, and
#: `app.lab.health` then reads the difference as drift and halts every arm on
#: it. A new version means a new tournament row, which is what 1.1.0 did.
SPEC_VERSION = "gradlive-1.5.0"

#: Each live arm and the paper arm it mirrors. Recorded so a reader can put the
#: real book beside the arm it is supposed to be copying, and so nothing has to
#: infer the mapping from a truncated id.
#:
#: The four-minute twin was added 2026-09-17 (1.1.0). Counting every trade,
#: including the pre-fix rugs the board leaves out, it was the only B3 hold
#: still ahead: those pools drained between minute four and six, and the
#: five-minute hold sat through four of them where the four-minute one sat
#: through one. Three events decide that, so it is an option, not a finding.
PAPER_BOOKS = {"G-B3-5M": "B3_198k_5m", "G-B3-4M": "B3_198k_4m",
               "G-BAS-5M": "BASE_75k_5m", "G-QUIET": "BASE_75k_quiet_5m",
               "G-QUIET4": "BASE_75k_quiet_4m"}
#: The same mapping read the other way: the live arm a paper entry feeds.
MIRRORS = {book: sid for sid, book in PAPER_BOOKS.items()}

#: The pool floor the paper arm buys above. Not enforced here — the graduation
#: recorder's own entry rule decides, and this registry only mirrors what it
#: chose — but stated because it is the single most load-bearing number in the
#: strategy: measured over 2,087 graduations, tokens above it collapse >80%
#: within five minutes at 0.47% against 13.85% for the whole population.
POOL_FLOOR_USD = 198_000
#: Per arm, because the baseline buys a different population: every graduation
#: over $75k, which is where its 4.8% rug rate comes from against B3's 0.3%.
POOL_FLOORS = {"G-B3-5M": POOL_FLOOR_USD, "G-B3-4M": POOL_FLOOR_USD,
               "G-BAS-5M": 75_000, "G-QUIET": 75_000, "G-QUIET4": 75_000}

#: The largest trade size Start offers for an arm, where that is smaller than
#: `REAL_WALLET_ENTRY_SIZE_USD`.
#:
#: G-BAS-5M only. Walked over its own week with every rug counted, a $100
#: wallet trading $25 at a time was WIPED OUT by it; $20 survived at a low of
#: $14, $10 at $48, $5 at $72. Karthik chose to run it at $10 or less
#: (2026-09-17), and the picker enforces that rather than trusting the choice
#: to be remembered.
#:
#: Raised to $25 at Karthik's request on 2026-09-18, after being shown the
#: same walk re-run over 447 trades: $25 still WIPED OUT a $100 wallet, $20
#: ended +225% but fell to $17, $10 +115% with a low of $52. The board's own
#: size walk leaves rugged trades out and showed $25 at +360%; the cap is his
#: decision against the rugs-counted numbers, not a finding that $25 is safe.
#: It still stops $50 and $100.
MAX_TICKET_USD = {"G-BAS-5M": D("25")}


def pool_floor(strategy_id: str) -> int:
    """The pool depth this arm's paper book buys above."""
    return POOL_FLOORS.get(strategy_id.upper(), POOL_FLOOR_USD)


def max_ticket(strategy_id: str) -> Decimal | None:
    """The largest ticket this arm may be started at, or None for no cap."""
    return MAX_TICKET_USD.get(strategy_id.upper())


def _hours(minutes: int) -> float:
    """A hold in minutes, as the hours the shared exit rule reads.

    A float, not a Decimal, and the difference is 6 seconds of a 28-second
    margin. `exit_driver` computes `held_hours` as `total_seconds() / 3600`, so
    at exactly five minutes it holds the float 300/3600. Decimal(5)/Decimal(60)
    carries more digits than that float and is fractionally LARGER, so
    `held >= exit` stayed false at 5m00s and the position left on the next pass
    instead. `minutes / 60` is the same double as `minutes * 60 / 3600`, so the
    comparison is exact at the boundary.
    """
    return minutes / 60


def hold_minutes(strategy: Strategy) -> int:
    """The strategy's hold, in the minutes a reader is told."""
    return round((strategy.exits.time_exit_hours or 0) * 60)


#: How stale a decision may be when the wallet acts on it.
#:
#: The shared driver default is ten minutes, which is wrong here by an order of
#: magnitude. The hold is five minutes and the earliest collapse observed in
#: this arm's own 145 trades landed at 5m28s, so a decision acted on nine
#: minutes late buys a token at the edge of the cliff the strategy exists to
#: stay in front of. Sixty seconds is one driver tick.
MAX_DECISION_AGE_SECONDS = 60

#: The smallest trade size the operator may choose at Start.
#:
#: The network fee is flat in SOL, so it takes a bigger share of a smaller
#: trade. On the 2026-09-17 split replay, $2 and $1 trades lost money on every
#: arm and $4 left the best one about even; $5 is the smallest size at which
#: that arm still came out ahead.
MIN_TICKET_USD = D("5")

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
        exits=Exits(take_profit=None, stop_loss=None, time_exit_hours=_hours(5)),
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
    Strategy(
        id="G-B3-4M",
        name="GRADUATION-B3-4MIN",
        hypothesis=(
            "The same deep-pool graduation, sold a minute sooner: the pools "
            "that drained under the five-minute hold did it between minute "
            "four and minute six."
        ),
        checkpoint_minutes=0,
        entry=(),
        size_usd=D("100"),
        max_concurrent=10,
        max_exposure_usd=D("1000"),
        exits=Exits(take_profit=None, stop_loss=None, time_exit_hours=_hours(4)),
        evidence="FORWARD_PAPER_255_TRADES_OVER_3_DAYS",
        overfit_risk="HIGH",
        note=(
            "NOT CALLED by the graduation lab's own gate. With every trade "
            "counted, the pre-fix rugs included, B3_198k_4m took a $100 wallet "
            "to $196 where the five-minute hold ended at $53 (2026-09-17) — a "
            "gap made by three rugs. Registered so it CAN be nominated; "
            "nominating it is a separate decision and starting it is the "
            "operator's alone."
        ),
    ),
    Strategy(
        id="G-BAS-5M",
        name="GRADUATION-BASELINE-5MIN",
        hypothesis=(
            "Every pump.fun graduation whose pool clears $75k, held five "
            "minutes. The board's BASELINE: it selects nothing, so it is the "
            "population each selection rule claims to beat."
        ),
        checkpoint_minutes=0,
        entry=(),
        size_usd=D("100"),
        max_concurrent=10,
        max_exposure_usd=D("1000"),
        exits=Exits(take_profit=None, stop_loss=None, time_exit_hours=_hours(5)),
        evidence="FORWARD_PAPER_356_TRADES_OVER_5_DAYS",
        overfit_risk="HIGH",
        note=(
            "REGISTERED AT KARTHIK'S REQUEST, 2026-09-17, against its own "
            "numbers. Its board return is one trade: +1,044% of a +1,195-point "
            "total, and without its best three trades 356 of them come to +84 "
            "points, about a quarter of a percent each. It rugs at 4.8% "
            "against B3's 0.3%, because a $75k floor admits the population B3 "
            "excludes. Walked with every rug counted it WIPED OUT a $100 "
            "wallet trading $25; `MAX_TICKET_USD` caps it at $25 all the same, "
            "at Karthik's request on 2026-09-18 (see its comment). "
            "It is also the board's control: an arm that exists to be the "
            "comparison is not evidence of an edge. Nominating it is a "
            "separate decision and starting it is the operator's alone."
        ),
    ),
    Strategy(
        id="G-QUIET",
        name="GRADUATION-QUIET-5MIN",
        hypothesis=(
            "The baseline's own coins, minus the ones a crowd has already "
            "found: a graduation over $75k whose pool has had fewer than 100 "
            "transactions when the book buys, held five minutes. Measured "
            "over 579 of the baseline's trades, the rug rate runs 3.1% under "
            "60 transactions and 23.7% over 400."
        ),
        checkpoint_minutes=0,
        entry=(),
        size_usd=D("100"),
        max_concurrent=10,
        max_exposure_usd=D("1000"),
        exits=Exits(take_profit=None, stop_loss=None, time_exit_hours=_hours(5)),
        evidence="FORWARD_PAPER_63_TRADES_OVER_16_HOURS",
        overfit_risk="HIGH",
        note=(
            "REGISTERED AT KARTHIK'S REQUEST, 2026-09-21, with its evidence "
            "stated against it. ITS TEST IS NOT FINISHED: the pre-registered "
            "judge is 150 closed trades or seven days, beating BASE_75k_5m "
            "over the same window AND without its best day. At registration "
            "it had 63 trades and was BEHIND that control on money ($103 "
            "against $112), and neither book had met a rug — the window has "
            "had none to dodge, so the rule has not been tested at all. The "
            "same rule on a $25k floor is the worst arm on the board "
            "(-13.8% a trade over 41 trades), which is the opposite of what "
            "the hypothesis predicts. Nominating it is a separate decision "
            "and starting it is the operator's alone."
        ),
    ),
    Strategy(
        id="G-QUIET4",
        name="GRADUATION-QUIET-4MIN",
        hypothesis=(
            "G-QUIET's coins on a four-minute clock. Replayed minute by "
            "minute over 771 baseline trades, gross of the ~1.1% round trip: "
            "+0.89% at two minutes, +1.19% at three, +1.93% at four, +1.76% "
            "at five, with 14 coins already down 80% by four minutes against "
            "20 by five. The fifth minute is where the drains land and the "
            "gains have stopped growing."
        ),
        checkpoint_minutes=0,
        entry=(),
        size_usd=D("100"),
        max_concurrent=10,
        max_exposure_usd=D("1000"),
        exits=Exits(take_profit=None, stop_loss=None, time_exit_hours=_hours(4)),
        evidence="FORWARD_PAPER_108_TRADES_PLUS_A_SEEDED_REPLAY",
        overfit_risk="HIGH",
        note=(
            "REGISTERED AT KARTHIK'S REQUEST, 2026-09-22, the morning after "
            "AROS: its pool held $365,302 at the buy and $372,041 at four "
            "minutes, then $404 at five. The four-minute book sold it at "
            "+3.1%; G-QUIET sat through the drain and the real wallet lost "
            "$25.00, the whole ticket. Over that whole day the four-minute "
            "book ran -1.20% a trade against -4.65%. "
            "WHAT IS NOT SETTLED: this is one drain. On the previous quiet "
            "day the same replay had four minutes BEHIND five (+1.45% "
            "against +2.21% a trade) — a shorter hold gives up real upside "
            "and only pays when a pool is drained inside the fifth minute, "
            "and it is defenceless against one drained in the third. Its "
            "book's first 82 trades are a SEEDED REPLAY of G-QUIET's coins "
            "re-priced at four minutes, not trades it took itself; only rows "
            "opened after 2026-09-21 18:49 UTC are forward evidence. "
            "Nominating it is a separate decision and starting it is the "
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
         "paper_books": PAPER_BOOKS,
         "pool_floor_usd": POOL_FLOOR_USD,
         "max_decision_age_s": MAX_DECISION_AGE_SECONDS,
         "strategies": [clean(s) for s in STRATEGIES]},
        sort_keys=True, separators=(",", ":"), default=str,
    )


SPEC_HASH = hashlib.sha256(_canonical().encode()).hexdigest()

# --- invariants ---------------------------------------------------------------
# Each of these is a property something downstream relies on, asserted here so a
# later edit fails at import rather than in production.

assert set(POOL_FLOORS) == set(BY_ID), "every arm states the floor it buys above"
assert set(MAX_TICKET_USD) <= set(BY_ID), "a ticket cap names an arm that exists"
assert all(cap >= MIN_TICKET_USD for cap in MAX_TICKET_USD.values()), (
    "a cap below the smallest ticket Start offers would leave an arm that "
    "cannot be started at all")
assert set(PAPER_BOOKS) == set(BY_ID) and len(MIRRORS) == len(PAPER_BOOKS), (
    "every live arm mirrors exactly one paper book, and no book feeds two arms"
)
assert all(len(s.id) <= 8 for s in STRATEGIES), (
    "lab_decisions.strategy_id is String(8); a longer id does not round-trip"
)
for _s in STRATEGIES:
    assert _s.exits.time_exit_hours, (
        "the clock is the strategy; without it there is no exit at all")
    assert _s.exits.take_profit is None, (
        "58 exit rules were replayed and the best changed one trade of 136")
    assert _s.exits.stop_loss is None, (
        "a stop on a 43-second feed fills below its own trigger; measured worse")
    assert _s.size_usd * _s.max_concurrent <= STARTING_EQUITY, (
        "the book cannot fund its own concurrency")
    assert MAX_DECISION_AGE_SECONDS < hold_minutes(_s) * 60, (
        "a decision older than the hold buys the token at the cliff, not before it")
del _s

__all__ = ["BY_ID", "FAILURE_EQUITY_FLOOR", "MAX_DECISION_AGE_SECONDS",
           "MIN_TICKET_USD", "MIRRORS", "PAPER_BOOKS", "POOL_FLOOR_USD", "SPEC_HASH",
           "SPEC_VERSION", "STARTING_EQUITY", "STRATEGIES", "hold_minutes"]
