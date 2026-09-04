"""What the leader just did, decoded from Helius.

Read-only and stateless. It answers one question — which tokens did this
wallet buy or sell recently — and the service decides what to do about it.

## The filter is not an optimisation, it is the difference between working
## and silently never trading

Helius is asked for `type=SWAP` SERVER-SIDE. Fetching his last hundred
transactions unfiltered and sorting them here returns, in practice, ZERO
trades: measured on this wallet on 2026-09-04, the most recent 100 transactions
were 95 TRANSFERs and 5 account initialisations spanning four hours — he
receives roughly twenty-five airdrop dust transfers an hour, which floods his
own trading out of any unfiltered window. The same request with `type=SWAP`
returned 21 real swaps across three days.

The lab shipped with client-side filtering and ticked green while seeing
nothing at all, which is the failure this comment exists to stop somebody
reintroducing.

The client-side check is kept as a second gate: the API filter is theirs and
could change, and a TRANSFER that reached here would otherwise be treated as a
trade. Belt and braces, cheap.

Side comes from the SOL leg, read from `accountData.nativeBalanceChange` for
the leader's own account: SOL out means he bought the token, SOL in means he
sold it. That figure is authoritative and already net of fees, unlike a sum of
`nativeTransfers`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.pumpfun import spec

logger = get_logger(__name__)

WSOL = "So11111111111111111111111111111111111111112"
DEX_SOURCES = {"JUPITER", "RAYDIUM", "PUMP_FUN", "PUMP_AMM", "ORCA",
               "METEORA", "PHOENIX"}
_BASE = "https://api.helius.xyz/v0/addresses"


@dataclass(frozen=True, slots=True)
class LeaderTrade:
    signature: str
    mint: str
    side: str                  # "buy" | "sell"
    #: What HE staked, when it can be seen at all. Context only — we size from
    #: our own book — and OPTIONAL on purpose: most of his swaps settle their
    #: SOL leg somewhere we cannot attribute, and refusing those trades to
    #: obtain a number we never use would throw away most of the feed.
    sol_amount: float | None
    at: datetime

    @property
    def age_seconds(self) -> float:
        return (datetime.now(UTC) - self.at).total_seconds()


def _is_swap(tx: dict[str, Any]) -> bool:
    return tx.get("type") == "SWAP" or tx.get("source") in DEX_SOURCES


def _sol_delta(tx: dict[str, Any], addr: str) -> int:
    """Native SOL moved for this account, fees included. Often zero here."""
    for a in tx.get("accountData") or []:
        if a.get("account") == addr:
            return int(a.get("nativeBalanceChange") or 0)
    return 0


def _our_token_changes(tx: dict[str, Any], addr: str) -> list[tuple[str, int]]:
    """Every token balance change belonging to THIS wallet, as (mint, raw).

    `accountData[].tokenBalanceChanges` is the authoritative record of what a
    wallet actually gained or lost, and it is the only field that survives how
    the trade was routed. The obvious alternatives both failed on this leader,
    measured on 2026-09-04 over his last 21 swaps:

      * `tokenTransfers` naming him directly    — missed 4, he routes through
                                                  aggregator accounts
      * `nativeBalanceChange` for the SOL leg   — zero on 13, he trades wrapped
      * `events.swap`                           — present on 13, and on some of
                                                  those the parsed swap belongs
                                                  to another account entirely

    Reading his balances instead resolves 17 of 21.
    """
    out: list[tuple[str, int]] = []
    for a in tx.get("accountData") or []:
        for tb in a.get("tokenBalanceChanges") or []:
            if tb.get("userAccount") != addr:
                continue
            raw = (tb.get("rawTokenAmount") or {}).get("tokenAmount")
            mint = tb.get("mint")
            if mint and raw is not None:
                try:
                    out.append((mint, int(raw)))
                except (TypeError, ValueError):
                    continue
    return out


def _traded(tx: dict[str, Any], addr: str) -> tuple[str, str] | None:
    """(mint, side) for the token this wallet actually traded, or None.

    Side comes from the SIGN of his own balance change — up means he acquired
    it, down means he disposed of it — which is all a copier needs. The SOL
    amount is deliberately NOT required: we size from our own book, so a trade
    whose SOL leg cannot be attributed is still perfectly copyable.

    The largest absolute change wins when several tokens move, because a route
    through an intermediate token leaves small residues of it behind.
    """
    changes = [(m, a) for m, a in _our_token_changes(tx, addr)
               if m != WSOL and a != 0]
    if not changes:
        return None
    mint, amount = max(changes, key=lambda c: abs(c[1]))
    return mint, ("buy" if amount > 0 else "sell")


def _leader_sol(tx: dict[str, Any], addr: str) -> float | None:
    """His stake in SOL when it is visible, else None. Never load-bearing."""
    wsol = sum(a for m, a in _our_token_changes(tx, addr) if m == WSOL)
    native = _sol_delta(tx, addr)
    raw = abs(wsol) or abs(native)
    return round(raw / 1_000_000_000, 6) if raw else None


async def recent_trades(*, limit: int = 100) -> list[LeaderTrade]:
    """The leader's most recent swaps, newest first. `[]` on any failure.

    Never raises. A follower that crashed on a rate limit would stop the tick
    that also settles the book, and a missed poll is recoverable while a dead
    tick is not.
    """
    key = settings.HELIUS_API_KEY.get_secret_value()
    if not key:
        logger.warning("pumpfun_follower_no_key")
        return []
    url = f"{_BASE}/{spec.LEADER_ADDRESS}/transactions"
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            r = await client.get(url, params={
                "api-key": key, "limit": limit, "type": "SWAP",
            })
        if r.status_code != 200:
            logger.warning("pumpfun_follower_http", status=r.status_code)
            return []
        rows = r.json()
    except Exception:
        logger.exception("pumpfun_follower_failed")
        return []

    out: list[LeaderTrade] = []
    for tx in rows:
        if not _is_swap(tx):
            continue
        traded = _traded(tx, spec.LEADER_ADDRESS)
        ts = tx.get("timestamp")
        if traded is None or not ts:
            continue
        mint, side = traded
        out.append(LeaderTrade(
            signature=tx["signature"], mint=mint, side=side,
            sol_amount=_leader_sol(tx, spec.LEADER_ADDRESS),
            at=datetime.fromtimestamp(ts, tz=UTC),
        ))
    out.sort(key=lambda t: t.at, reverse=True)
    return out
