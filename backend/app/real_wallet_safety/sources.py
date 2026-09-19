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
#: rugged, found by replaying BASE_75k_5m's trades on-chain (15-18 Sep 2026),
#: and the wallets that pulled a pool themselves. On the trades replayed, each
#: cost less blocked than traded. Karthik asked for it, 2026-09-18.
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
    # The wallets that pulled the pool THEMSELVES in B3_198k_4m's two on-chain
    # rugs: each put ~99% of its pool's SOL in at launch and took 82-96% of it
    # back in one sale ~2 min after the buy. Karthik asked, 2026-09-18.
    # ZBCN (17 Sep, -$46.38 on the wallet): its pool buyer, still launching
    # (26 of the book's 379 trades, -$11 at $25 with its dump counted), and
    # the one-shot account that funded it.
    "GBdQ1Vz6Mw2Nx5TLs61KS3GsJBwccKGj9zxZZD4FWuaK",
    "6JqtR1h3QZ5BumnbKhtUXPsFaZcrRrBoi5ae3HLB8iVT",
    # WWR (18 Sep, -$9.92): its pool buyer and its curve buyer, both emptied
    # since. Their funders are left out on purpose: 34nDrS holds ~2,950 SOL and
    # sends 1,000 transactions in 6 minutes (an exchange), 96UiVw seeded wallets
    # at 1,000 in 12 minutes (a service). Blocking either could refuse coins
    # that have nothing to do with WWR.
    "6cb6cF9EeDvjuerUR3h9zWNFL3bKmNnvnomJ24qhKUJ7",
    "8EdVxQ78Y4DQJsqSmnkH1ySPGu1sqab8WAYL8mgFCt9j",
    # Each of these rugs was ONE operator: its curve buyer (funded off an
    # exchange) sent ~5,000 SOL through a one-shot account to its pool buyer,
    # which filled the pool and later pulled it. ZBCN's curve buyer, left out
    # above, is that operator's main wallet. Karthik asked, 2026-09-19.
    "8eEQ6s6gNykb9sFhS5aihsxMenTTqZkm25EqNNFaDvwf",
    # COST (18 Sep 21:35, -$43.24 on the wallet at $50): the pool buyer took
    # 702 of its 989 SOL back 15 s after the wallet's buy. Its curve buyer, the
    # one-shot account between them, and the pool buyer. Their other funder,
    # 5tzFki, is an exchange hot wallet (~2M SOL) and stays OFF this list.
    "2Cghr56XrPXRAJhzVRor2pSnDFYVe2t2guKgdzNSjQsT",
    "wqcTmHNuzxihz8bSckYd5e7n8zBUgtLGEWhXfuoS1gv",
    "EvfSd1qWRKLmCzoD66mi64fehEikgHYdJv5s67FBqtmE",
    # Repeat operators among BASE_75k_5m's 31 rugs (15-19 Sep): 18 of the 30
    # traced came from three, linked by shared wallets. Karthik asked, 2026-09-19.
    # The 16 Sep wave's pool buyers (its funders are listed above): on 8 and 3
    # of its 11 rugs.
    "E7mdTgYspRGRAE1zJoUW8zdxNU5VjpQbivXU6huB7oqJ",
    "5MYVpHEiLHkddGHQhZMfhwSVqYi3yzmpmGfRxSeavBvL",
    # SUUB, SOLCAT, WEN, Pump, ELIEN (18 Sep): this pool buyer bought all five
    # (xZJADx above funded it). Its curve funder, 8zxkme, stays off: ~930 SOL and
    # 1,000 transactions in half an hour looks like a service.
    "BGCbX7bcXAnbKuUP9uUfAGzQyZRz158kAzYPNKpTLCe2",
    # FOMO and AMAZON (18 Sep, an hour apart): the same big wallet. Their shared
    # funder, BZXZ8d, stays off: 578 transactions in 36 minutes, a seeder.
    "DdtsVPAnET6MqDPvDumgUBsTYpYcn7UZpKMG8uwJzJyo",
    # KIBA (19 Sep 07:00, -99% in every book incl. B3_198k_4m and E75T_4m): its
    # launch wallet put 1,534 SOL in (4 clean coins before, so it looked
    # proven); a new wallet funded through a one-shot account sold 28% of the
    # coins from 47 s after the buy and took 1,953 SOL. Launch wallet, dumper,
    # one-shot funder. Karthik asked, 2026-09-19. The busy funder behind the
    # launch wallet (4gwSSV, 272 coins) stays off.
    "9x2N1MHxs5NxAYnpkNi1QbyE3ayk6oqh53p9vpVjDdHa",
    "FtvDtRoKP7vBPwwow1W5uttUVnXoskZ5bFnpkijb1iwL",
    "3YfWwbV9QZbGfyQWHKGANdK8iwnMcpdWj1E2SqMvWkc6",
})


@dataclass(frozen=True, slots=True)
class Sources:
    wallets: tuple[str, ...]
    funders: tuple[str, ...]
    #: SOL each wallet got in that first payment, in `wallets` order; None
    #: where it could not be traced. Recorded, not yet judged: on BASE's
    #: replayed trades the coins whose big wallets were funded with under
    #: 100 SOL held 15 of 23 rugs (-$177 at $20 a trade) while the rest made
    #: money every day - but 16 Sep alone was -$168 of it, so it is being
    #: measured forward before it is allowed to refuse anything.
    funded_sol: tuple[Decimal | None, ...] = ()

    def ids(self) -> set[str]:
        return set(self.wallets) | set(self.funders)

    def as_json(self) -> dict[str, list]:
        return {"wallets": list(self.wallets), "funders": list(self.funders),
                "funded_sol": [None if x is None else float(round(x, 4))
                               for x in self.funded_sol]}


def _keys(tx: dict[str, Any]) -> list[str]:
    keys = ((tx.get("transaction") or {}).get("message") or {}).get("accountKeys") or []
    return [k["pubkey"] if isinstance(k, dict) else k for k in keys]


async def funder(rpc: SolanaRPC, wallet: str) -> str | None:
    """Who paid SOL into `wallet` the first time it got any; see `funding`."""
    found = await funding(rpc, wallet)
    return found[0] if found else None


async def funding(rpc: SolanaRPC, wallet: str) -> tuple[str, Decimal] | None:
    """Who paid SOL into `wallet` the first time it got any - the account whose
    balance fell most in that transaction - and how much SOL `wallet` got.
    None when its oldest transactions never paid it (a wallet that only ever
    spent is not one we can trace)."""
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
                return max(paid)[1], Decimal(post[i] - pre[i]) / 10**9
        token = page.get("paginationToken")
        if not token:
            break
    return None


async def trace(rpc: SolanaRPC, wallets: list[str]) -> Sources:
    """The given wallets, whoever funded each, and with how much."""
    found = await asyncio.gather(*(funding(rpc, w) for w in wallets))
    return Sources(wallets=tuple(wallets), funders=tuple(f[0] for f in found if f),
                   funded_sol=tuple(None if f is None else f[1] for f in found))


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
