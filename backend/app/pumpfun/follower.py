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
    side: str          # "buy" | "sell"
    sol_amount: float  # absolute, informational only — we size ourselves
    at: datetime

    @property
    def age_seconds(self) -> float:
        return (datetime.now(UTC) - self.at).total_seconds()


def _is_swap(tx: dict[str, Any]) -> bool:
    return tx.get("type") == "SWAP" or tx.get("source") in DEX_SOURCES


def _sol_delta(tx: dict[str, Any], addr: str) -> int:
    for a in tx.get("accountData") or []:
        if a.get("account") == addr:
            return int(a.get("nativeBalanceChange") or 0)
    return 0


def _mint(tx: dict[str, Any], addr: str) -> str | None:
    for t in tx.get("tokenTransfers") or []:
        m = t.get("mint")
        if (m and m != WSOL
                and addr in (t.get("fromUserAccount"), t.get("toUserAccount"))):
            return m
    return None


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
        mint = _mint(tx, spec.LEADER_ADDRESS)
        if not mint:
            continue
        delta = _sol_delta(tx, spec.LEADER_ADDRESS)
        if delta == 0:
            continue
        ts = tx.get("timestamp")
        if not ts:
            continue
        out.append(LeaderTrade(
            signature=tx["signature"], mint=mint,
            side="buy" if delta < 0 else "sell",
            sol_amount=abs(delta) / 1_000_000_000,
            at=datetime.fromtimestamp(ts, tz=UTC),
        ))
    out.sort(key=lambda t: t.at, reverse=True)
    return out
