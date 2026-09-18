"""Who holds a coin at the moment the wallet is about to buy it.

Every rug that cost real money was one wallet already sitting on a sixth to a
fifth of the supply when the wallet bought — ZBCN 19.1%, WWR 19.9%, SUUB 16.9%
(17-18 Sep 2026) — beside a pool holding far fewer tokens, so that selling part
of the bag drained it. SUUB's dumper did not move once between the buy and the
dump. Holders AT GRADUATION cannot see this: 85% of these coins are bought out
by one wallet at launch, rugs and winners alike, and it is the minute after,
when that wallet spreads its bag, that separates them. So this reads at the buy.

`getTokenLargestAccounts` names token ACCOUNTS, not wallets. One more read turns
them into owners, which is how the pool's own vault is told apart from a holder
and how one wallet's several accounts count as one bag.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.models.research_data import HolderSnapshot
from app.services.rpc.base import SolanaRPC

#: Bags within this fraction of each other are one bundle: several wallets that
#: bought together and split a position so no single one looks big (the 16 Sep
#: rugs were pairs and fours of 1.2-1.3% bags).
BUNDLE_TOLERANCE = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class Holders:
    supply: int
    #: (owner, raw amount), the pool excluded, largest first.
    wallets: tuple[tuple[str, int], ...]
    #: The pool's own token balance. None when the pool is not among the largest
    #: accounts at all — every listed wallet then holds more than it does.
    pool: int | None
    latency_ms: int

    def pct(self, raw: int) -> Decimal:
        return Decimal(raw) * 100 / self.supply if self.supply else Decimal(0)

    @property
    def top(self) -> int:
        return self.wallets[0][1] if self.wallets else 0

    @property
    def bundle(self) -> int:
        """Tokens held in bags that match another bag to within the tolerance."""
        amounts = [a for _, a in self.wallets if a > 0]
        total, i = 0, 0
        while i < len(amounts):
            j = i + 1
            while j < len(amounts) and amounts[j] >= amounts[i] * (1 - BUNDLE_TOLERANCE):
                j += 1
            if j - i >= 2:
                total += sum(amounts[i:j])
            i = j
        return total

    def summary(self) -> dict[str, object]:
        return {
            "top_pct": str(round(self.pct(self.top), 2)),
            "pool_pct": None if self.pool is None else str(round(self.pct(self.pool), 2)),
            "bundle_pct": str(round(self.pct(self.bundle), 2)),
            "wallets": len(self.wallets),
            "latency_ms": self.latency_ms,
        }


def reasons(h: Holders, *, max_pct: Decimal, max_vs_pool: Decimal | None = None,
            max_bundle_vs_pool: Decimal | None = None) -> list[str]:
    """Why these holders refuse a buy; empty when they do not.

    One wallet over `max_pct` of the supply. The two pool rules — one wallet, or
    a bundle, holding more than that many times the pool's own tokens — refuse
    only when given a threshold. Measured on real coins on 2026-09-18, pools
    commonly hold just 1-4% of the supply once the buying drains them, so at 1x
    those rules refused winners too (Forbes, +12%); until the recorded holders
    show where rugs and winners part, they are measured and stored, not applied.
    With the pool absent from the largest accounts every listed wallet
    out-holds it, so an applied pool rule trips.
    """
    out: list[str] = []
    if h.pct(h.top) > max_pct:
        out.append("HOLDER_TOO_LARGE")
    if max_vs_pool is not None and h.top and (h.pool is None or h.top > h.pool * max_vs_pool):
        out.append("HOLDER_BIGGER_THAN_POOL")
    if (max_bundle_vs_pool is not None and h.bundle
            and (h.pool is None or h.bundle > h.pool * max_bundle_vs_pool)):
        out.append("BUNDLE_BIGGER_THAN_POOL")
    return out


#: A person's wallet is an account the System Program owns. Anything else a
#: token account belongs to — a pool, a curve, a vault authority — is a
#: program's, and its tokens are liquidity, not a bag anyone can dump.
SYSTEM_PROGRAM = "11111111111111111111111111111111"


def _parsed(info: dict[str, Any] | None) -> dict[str, Any]:
    return ((((info or {}).get("data") or {}).get("parsed") or {}).get("info")) or {}


async def read(rpc: SolanaRPC, mint: str) -> Holders:
    """Three reads, one after another: the largest accounts; the mint and those
    accounts together (the supply, and who owns each account); and whether each
    owner is a person or a program.

    The supply comes off the mint account in the second read rather than from
    `getTokenSupply`, which took 0.2-2.9s on fresh coins against ~30ms for the
    batch it now rides in — and this sits in front of a five-minute trade.

    The pool is found by what it IS rather than by an address handed in: the
    address a market snapshot names can be another of the coin's pools
    (DexScreener switches between them), and a pool the reader fails to find
    reads as "every wallet out-holds the pool".
    """
    started = time.monotonic()
    confirmed = {"commitment": "confirmed"}
    largest = await rpc.call("getTokenLargestAccounts", [mint, confirmed])
    accounts = [(a["address"], int(a["amount"])) for a in (largest or {}).get("value") or []]
    infos = await rpc.call("getMultipleAccounts", [
        [mint] + [a for a, _ in accounts], {"encoding": "jsonParsed", **confirmed}])
    values = (infos or {}).get("value") or []
    supply = int(_parsed(values[0] if values else None)["supply"])
    owned = [(_parsed(info).get("owner") or address, amount)
             for (address, amount), info in zip(accounts, values[1:], strict=False)]
    owners = list(dict.fromkeys(o for o, _ in owned))
    kinds = await rpc.call("getMultipleAccounts", [owners, {
        "encoding": "base64", "dataSlice": {"offset": 0, "length": 0}, **confirmed}])
    # An owner with no account at all is kept as a person: counting a bag it
    # should not is a refused buy, and missing one is a rug.
    program = {o for o, k in zip(owners, (kinds or {}).get("value") or [], strict=False)
               if k is not None and k.get("owner") != SYSTEM_PROGRAM}
    bags: dict[str, int] = {}
    pool_raw: int | None = None
    for owner, amount in owned:
        if owner in program:
            pool_raw = (pool_raw or 0) + amount
        else:
            bags[owner] = bags.get(owner, 0) + amount
    return Holders(
        supply=supply,
        wallets=tuple(sorted(bags.items(), key=lambda kv: -kv[1])),
        pool=pool_raw,
        latency_ms=int((time.monotonic() - started) * 1000),
    )


def to_row(h: Holders | None, mint: str, context: str, *, at: datetime,
           failure: str | None = None) -> HolderSnapshot:
    """One `holder_snapshots` row: `largest_nonpool_pct` is the figure the gate
    judges; `top1_pct` includes the pool, as the older collector's rows do. The
    ten largest wallets, the pool's tokens and the bundle go in `accounts`, so a
    pool or bundle rule can be tried against them later without a re-read."""
    if h is None:
        return HolderSnapshot(mint_address=mint, captured_at=at, provider="helius",
                              context=context, failure_reason=(failure or "unreadable")[:64])
    return HolderSnapshot(
        mint_address=mint, captured_at=at, provider="helius", context=context,
        supply_raw=Decimal(h.supply),
        top1_pct=round(h.pct(max(h.top, h.pool or 0)), 4),
        largest_nonpool_pct=round(h.pct(h.top), 4),
        accounts={"wallets": [[o, a] for o, a in h.wallets[:10]],
                  "pool_raw": h.pool, "bundle_raw": h.bundle},
        rpc_latency_ms=h.latency_ms, rpc_fallback_used=False,
    )
