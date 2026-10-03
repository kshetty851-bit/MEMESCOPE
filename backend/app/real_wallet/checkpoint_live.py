"""The Checkpoint, live: where each new graduation is in the thirty checks.

Karthik, 2026-10-02: "i want real time token checks". Every coin that
graduated in the last few minutes, placed at the check it has reached, from
what each check has recorded so far — never from a guess:

  Hatch      the graduation itself (`grad_migrations`)
  Depth      the pool's first reading (`grad_postgrad_samples`), ~30s on
  Rug blocks `grad_operators.blocked_reason`
  Hush       the rule's quiet book bought it (passed) or only the
             buy-everything book did (too busy)
  Gate       the main wallet placed its buy; if not, and it was already
             holding a coin (one at a time), that is Limit; otherwise the
             reason is not recorded and the coin says so, on no robot
  Safety     the safety evaluation: the first REJECT reason, or ALLOW
  Wallet     the main wallet's position opened

Robots are named by their ids in `frontend/src/lib/hq/checkpoint.ts`; a stop
by a refusal code carries the code and the page maps it to its robot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

POOL_FLOOR_USD = Decimal(75_000)
#: How long to wait for a pool reading before calling it missing.
POOL_WAIT = timedelta(minutes=3)
#: The rule decides within a few minutes of the pool showing.
RULE_WAIT = timedelta(minutes=4)
#: The wallet acts within seconds of its rule's entry.
GATE_WAIT = timedelta(seconds=90)
BASELINE_BOOK = "BASE_75k_5m"
#: The main wallet's own book: the gate, safety and wallet stages are its.
QUIET_BOOK = "BASE_75k_quiet_5m"

#: Karthik, 2026-10-03: "in karthik lab only show as 50k pool". Each pool rule
#: the belt can be drawn for, and the books whose buys show its Hush decision.
#: $50k is HIS book's rule, built the way his book is (`KARTHIK_BOOK_POOLS`):
#: the $75k quiet arm above $75k and KARTHIK_Q50_5M on $50-75k pools. There is
#: no buy-everything book on $50-75k pools, so "too busy" can only be told
#: there for $75k+ coins; a $50-75k coin the rule passed over says only that.
QUIET_BOOKS: dict[int, tuple[str, ...]] = {75_000: (QUIET_BOOK,),
                                           50_000: (QUIET_BOOK, "KARTHIK_Q50_5M")}
BASELINE_BOOKS: tuple[str, ...] = (BASELINE_BOOK,)


@dataclass
class Coin:
    graduated: datetime
    liquidity: Decimal | None = None
    blocked: str | None = None
    books: dict[str, datetime] = field(default_factory=dict)
    intent_at: datetime | None = None
    #: (evaluated_at, decision, reason_codes), oldest first.
    evaluations: list[tuple[datetime, str, list[str]]] = field(default_factory=list)
    bought_at: datetime | None = None
    #: The main wallet already held a coin when the rule took this one.
    wallet_busy: bool = False


def where(coin: Coin, now: datetime, *, floor: Decimal = POOL_FLOOR_USD,
          quiet_books: tuple[str, ...] = (QUIET_BOOK,),
          baseline_books: tuple[str, ...] = BASELINE_BOOKS) -> dict[str, Any]:
    """`status` checking/stopped/bought; `robot` (an id) or `code` (a refusal
    code the page maps to its robot) or neither; `note` in plain words.

    `floor` and the books are the pool rule the belt is drawn for (see
    `QUIET_BOOKS`); the defaults are the main wallet's own $75k rule."""
    def out(status: str, note: str, robot: str | None = None,
            code: str | None = None) -> dict[str, Any]:
        return {"status": status, "robot": robot, "code": code, "note": note}

    if coin.bought_at is not None:
        return out("bought", "passed all 30 and was bought", robot="wallet")
    # Karthik, 2026-10-03: under a lower floor than the main wallet's, a coin
    # under ITS floor that its book never took is not the main wallet's, so
    # the wallet records cannot speak for it. Safety evaluations carry no
    # wallet: USER 1's G-Q50 buys these pools, and its checks would otherwise
    # show here as the main wallet "signing the buy".
    beneath = (floor < POOL_FLOOR_USD and QUIET_BOOK not in coin.books
               and coin.liquidity is not None and coin.liquidity < POOL_FLOOR_USD)
    after = [] if beneath else [e for e in coin.evaluations if e[0] >= coin.graduated]
    if after:
        _at, decision, codes = after[-1]
        if decision == "REJECT":
            return out("stopped", "refused by the safety check",
                       code=codes[0] if codes else None)
        return out("checking", "passed the safety check, signing the buy", robot="roundtrip")
    if coin.intent_at is not None and not beneath:
        return out("checking", "the wallet is buying; safety check running", robot="probe")
    if coin.liquidity is None:
        if now - coin.graduated > POOL_WAIT:
            return out("stopped", "its pool never showed", robot="depth")
        return out("checking", "waiting for the pool to show", robot="depth")
    if coin.liquidity < floor:
        return out("stopped", f"pool ${coin.liquidity:,.0f}, under ${floor:,.0f}",
                   robot="depth")
    if coin.blocked:
        return out("stopped", "a rug block refused it", code=coin.blocked)
    if QUIET_BOOK in coin.books:
        if now - coin.books[QUIET_BOOK] <= GATE_WAIT:
            return out("checking", "passed the rule; at the wallet gate", robot="switch")
        if coin.wallet_busy:
            return out("stopped", "the wallet was already holding a coin", robot="limit")
        return out("stopped",
                   "passed the rule; the wallet did not take it (reason not recorded)")
    if any(b in coin.books for b in quiet_books):
        # Passed the lower rule, which the main wallet does not trade: its own
        # end of the line, not a stop by any check, so no robot is blamed.
        return out("stopped", f"passed the ${floor:,.0f} rule; the main wallet "
                              f"buys ${POOL_FLOOR_USD:,.0f}+ pools only")
    if any(b in coin.books for b in baseline_books):
        return out("stopped", "pool too busy: 100+ trades", robot="hush")
    if now - coin.graduated > RULE_WAIT:
        return out("stopped", "the rule did not take it", robot="hush")
    return out("checking", "checking the pool is quiet", robot="hush")
