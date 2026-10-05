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

#: $50k since 2026-10-04: the wallets trade G-Q50 (quiet $50k+), whose paper
#: arm is BASE_50k_quiet_5m (Karthik: "showing pool check under 75k instead of
#: 50k ... fix it").
POOL_FLOOR_USD = Decimal(50_000)
#: How long to wait for a pool reading before calling it missing.
POOL_WAIT = timedelta(minutes=3)
#: The rule decides within a few minutes of the pool showing.
RULE_WAIT = timedelta(minutes=4)
#: The wallet acts within seconds of its rule's entry.
GATE_WAIT = timedelta(seconds=90)
BASELINE_BOOK = "BASE_75k_5m"
QUIET_BOOK = "BASE_50k_quiet_5m"


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


def where(coin: Coin, now: datetime) -> dict[str, Any]:
    """`status` checking/stopped/bought; `robot` (an id) or `code` (a refusal
    code the page maps to its robot) or neither; `note` in plain words."""
    def out(status: str, note: str, robot: str | None = None,
            code: str | None = None) -> dict[str, Any]:
        return {"status": status, "robot": robot, "code": code, "note": note}

    if coin.bought_at is not None:
        return out("bought", "passed all 30 and was bought", robot="wallet")
    after = [e for e in coin.evaluations if e[0] >= coin.graduated]
    if after:
        _at, decision, codes = after[-1]
        if decision == "REJECT":
            return out("stopped", "refused by the safety check", code=(codes or [None])[0])
        return out("checking", "passed the safety check, signing the buy", robot="roundtrip")
    if coin.intent_at is not None:
        return out("checking", "the wallet is buying; safety check running", robot="probe")
    if coin.liquidity is None:
        if now - coin.graduated > POOL_WAIT:
            return out("stopped", "its pool never showed", robot="depth")
        return out("checking", "waiting for the pool to show", robot="depth")
    if coin.liquidity < POOL_FLOOR_USD:
        return out("stopped", f"pool ${coin.liquidity:,.0f}, under ${POOL_FLOOR_USD:,.0f}",
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
    if BASELINE_BOOK in coin.books:
        return out("stopped", "pool too busy: 100+ trades", robot="hush")
    if now - coin.graduated > RULE_WAIT:
        return out("stopped", "the rule did not take it", robot="hush")
    return out("checking", "checking the pool is quiet", robot="hush")


#: The Pool Lab's $10k paper book (2026-10-05): the office in its $10k mode.
POOL_FLOOR_10K = Decimal(10_000)
POOL_10K_BOOK = "POOL_10K_QUIET_3M"


def where_pool(coin: Coin, now: datetime,
               floor: Decimal = POOL_FLOOR_10K) -> dict[str, Any]:
    """`where` for a paper book with no wallet behind it: a coin is BOUGHT
    when the book bought it (`coin.bought_at`), and the wallet's gate and
    safety lab have nothing to say. Pools under $50k carry no rug-block record
    (the lab records the wallets behind $50k+ pools only)."""
    def out(status: str, note: str, robot: str | None = None,
            code: str | None = None) -> dict[str, Any]:
        return {"status": status, "robot": robot, "code": code, "note": note}

    if coin.bought_at is not None:
        return out("bought", "passed the checks; the $10k paper book bought it",
                   robot="wallet")
    if coin.liquidity is None:
        if now - coin.graduated > POOL_WAIT:
            return out("stopped", "its pool never showed", robot="depth")
        return out("checking", "waiting for the pool to show", robot="depth")
    if coin.liquidity < floor:
        return out("stopped", f"pool ${coin.liquidity:,.0f}, under ${floor:,.0f}",
                   robot="depth")
    if coin.blocked:
        return out("stopped", "a rug block refused it", code=coin.blocked)
    if now - coin.graduated > RULE_WAIT:
        return out("stopped", "the rule did not take it (a busy pool, or a late entry)",
                   robot="hush")
    return out("checking", "checking the pool is quiet", robot="hush")
