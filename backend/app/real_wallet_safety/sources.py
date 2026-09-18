"""The money behind a coin's two big wallets, and whether it just rugged.

At the buy, every coin the wallet copies looks the same: one wallet that bought
the whole curve (~79.5% of the supply) and one that bought most of the new pool
(~17%). Rugs and winners alike, so no holder share tells them apart (482 BASE
trades replayed on 2026-09-18: 98.5% had a wallet over 10%). What does repeat
is the MONEY. An operator makes fresh wallets for every coin but funds them from
the same place: 11 of the 16-Sep rugs were funded by the same two accounts, and
SUUB and SOLCAT (18 Sep) shared theirs.

So after a rug, the wallets and the funders behind it are blocked for a few
hours, and the money behind the worst waves so far is blocked for good
(`ALWAYS_BLOCKED`). Replayed on-chain over 485 BASE trades at $20 a trade, blocking for
3 hours turned -$3 into +$127 (13 rugs instead of 24, 26 other trades skipped).
It cannot stop an operator's FIRST rug, only the ones after it.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.labs.graduation.models import GradPaperPosition
from app.models.real_wallet_execution import RealWalletPosition
from app.models.research_data import HolderSnapshot
from app.services.rpc.base import SolanaRPC

#: Pages of 25 of a wallet's oldest transactions searched for its funding.
FUNDING_PAGES = 2

#: Money blocked for good, not for three hours: funders whose coins MOSTLY
#: rugged, found by replaying BASE_75k_5m's trades on-chain (15-18 Sep 2026).
#: Blocking them costs almost no winners. Karthik asked for it, 2026-09-18.
#:
#: The big launch funders behind a single rug are deliberately NOT here: ZBCN's
#: funded 65 of the book's coins and one rugged, and four more funded 26-44
#: each with one or two. A standing block on them would skip dozens of winners
#: for every rug it avoided; the three-hour block catches their rugs' repeats.
ALWAYS_BLOCKED = frozenset({
    # One operator, 16 Sep 02:08-11:38: TRUMP, POT, baton, ALLINU, Benz,
    # TikTok, ARCH, FAIR, USWS, PONYX, YouTube. It funded the curve buyer
    # (11 rugs of its 20 coins) ...
    "DyaESzDfBLtbvKz7iM5Th6nsbsGSpjt5NLXuieigRcZX",
    # ... and the pool buyer (11 rugs of 19).
    "5W84xUtSNhMutNbT8XdgWrMShMgmjxjbQKK7zebdLaSn",
    # The pool buyer of SUUB and SOLCAT, 18 Sep: 2 rugs of its 3 coins.
    "xZJADxiqWhDneh6wUtAfRM3gRRpj4tjw7V7ExTPXQ7z",
})


@dataclass(frozen=True, slots=True)
class Sources:
    wallets: tuple[str, ...]
    funders: tuple[str, ...]

    def ids(self) -> set[str]:
        return set(self.wallets) | set(self.funders)

    def as_json(self) -> dict[str, list[str]]:
        return {"wallets": list(self.wallets), "funders": list(self.funders)}


def _keys(tx: dict[str, Any]) -> list[str]:
    keys = ((tx.get("transaction") or {}).get("message") or {}).get("accountKeys") or []
    return [k["pubkey"] if isinstance(k, dict) else k for k in keys]


async def funder(rpc: SolanaRPC, wallet: str) -> str | None:
    """Who paid SOL into `wallet` the first time it got any: the account whose
    balance fell most in that transaction. None when its oldest transactions
    never paid it (a wallet that only ever spent is not one we can trace)."""
    token: str | None = None
    for _ in range(FUNDING_PAGES):
        opts: dict[str, Any] = {
            "transactionDetails": "full", "encoding": "jsonParsed",
            "maxSupportedTransactionVersion": 1, "sortOrder": "asc", "limit": 25,
            "filters": {"status": "succeeded"}}
        if token:
            opts["paginationToken"] = token
        page = await rpc.call("getTransactionsForAddress", [wallet, opts]) or {}
        for tx in page.get("data") or []:
            keys = _keys(tx)
            meta = tx.get("meta") or {}
            pre, post = meta.get("preBalances") or [], meta.get("postBalances") or []
            if wallet not in keys:
                continue
            i = keys.index(wallet)
            if i >= len(post) or post[i] <= pre[i]:
                continue
            span = range(min(len(keys), len(pre), len(post)))
            paid = [(pre[j] - post[j], keys[j]) for j in span if j != i and pre[j] > post[j]]
            if paid:
                return max(paid)[1]
        token = page.get("paginationToken")
        if not token:
            break
    return None


async def trace(rpc: SolanaRPC, wallets: list[str]) -> Sources:
    """The given wallets and whoever funded each."""
    found = await asyncio.gather(*(funder(rpc, w) for w in wallets))
    return Sources(wallets=tuple(wallets), funders=tuple(f for f in found if f))


async def recent_rug_ids(
    session: AsyncSession, *, since: datetime, rug_return: Decimal
) -> set[str]:
    """Wallets and funders behind every rug that closed since `since`: a book
    trade or a wallet trade that got back `rug_return` or worse. Only coins the
    entry recorder traced have any; the rest teach nothing."""
    paper = select(GradPaperPosition.mint).where(
        GradPaperPosition.closed_at >= since,
        GradPaperPosition.net_return <= rug_return)
    mine = select(RealWalletPosition.mint_address).where(
        RealWalletPosition.status == "CLOSED",
        RealWalletPosition.closed_at >= since,
        RealWalletPosition.realised_net_pnl_usd.is_not(None),
        RealWalletPosition.entry_price_usd * RealWalletPosition.quantity > 0,
        RealWalletPosition.realised_net_pnl_usd
        / (RealWalletPosition.entry_price_usd * RealWalletPosition.quantity) <= rug_return)
    rows = await session.scalars(select(HolderSnapshot.accounts).where(
        HolderSnapshot.context.in_(("paper_entry", "wallet_gate")),
        HolderSnapshot.mint_address.in_(paper.union(mine))))
    out: set[str] = set()
    for accounts in rows:
        found = (accounts or {}).get("sources") or {}
        out |= set(found.get("wallets") or []) | set(found.get("funders") or [])
    return out
