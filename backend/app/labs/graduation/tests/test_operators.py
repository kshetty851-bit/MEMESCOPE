"""Reading a coin's operator: its big wallets and the money behind them."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.labs.graduation import sources

MINT = "Bjsxb2QErbB4rhpSRsUgtNBPPri24R3AK58tQwjvpump"
POOL = "PoolAddress1111111111111111111111111111111"


class FakeRPC:
    def __init__(self, largest: list[dict[str, Any]] | None, owners: dict[str, str]) -> None:
        self.largest, self.owners, self.asked = largest, owners, []

    async def call(self, method: str, params: Any) -> Any:
        self.asked.append((method, params))
        if method == "getTokenSupply":
            return {"value": {"uiAmountString": "1000000000"}}
        if method == "getTokenLargestAccounts":
            return None if self.largest is None else {"value": self.largest}
        if method == "getMultipleAccounts":
            return {"value": [{"data": {"parsed": {"info": {"owner": self.owners[a]}}}}
                              for a in params[0]]}
        wallet = params[0]
        # The wallet's first transaction: FunderX pays it 5 SOL.
        return {"data": [{"transaction": {"message": {"accountKeys": ["FunderX", wallet]}},
                          "meta": {"preBalances": [9_000_000_000, 0],
                                   "postBalances": [4_000_000_000, 5_000_000_000]}}]}


def row(address: str, whole_tokens: int) -> dict[str, Any]:
    return {"address": address, "uiAmountString": str(whole_tokens)}


async def test_the_operator_is_the_big_wallets_and_their_funders() -> None:
    rpc = FakeRPC([row("vault", 15_000_000), row("op_acct", 793_100_000),
                   row("dust_acct", 5_000_000)],
                  {"vault": POOL, "op_acct": "OpWallet"})
    # the pool's vault is not a wallet; a 0.5% bag is not an operator's
    assert await sources.operator_ids(rpc, MINT, POOL) == frozenset({"OpWallet", "FunderX"})


async def test_an_unreadable_holder_list_is_not_a_clean_stranger() -> None:
    assert await sources.operator_ids(FakeRPC(None, {}), MINT, POOL) is None
    # nobody over 1% besides the pool: readable, and nobody to vouch for
    rpc = FakeRPC([row("vault", 20_000_000)], {"vault": POOL})
    assert await sources.operator_ids(rpc, MINT, POOL) == frozenset()


async def test_the_holders_are_read_at_the_confirmed_block() -> None:
    """Finalized trails by ~13 s; an instant graduation read 5-8 s after its
    launch does not exist there yet, and 54 of 124 live reads came back empty."""
    rpc = FakeRPC([row("op_acct", 793_100_000)], {"op_acct": "OpWallet"})
    assert await sources.operator_ids(rpc, MINT, POOL) == frozenset({"OpWallet", "FunderX"})
    holder_reads = [p for m, p in rpc.asked if m != "getTransactionsForAddress"]
    assert len(holder_reads) == 3
    assert all(p[-1].get("commitment") == "confirmed" for p in holder_reads)


async def test_a_mint_the_index_does_not_know_yet_is_asked_again() -> None:
    """Seconds after launch the holder index answers "not a Token mint" even at
    confirmed; the read waits it out instead of recording a stranger."""
    from app.services.rpc.standard import RpcError

    class Lagging(FakeRPC):
        misses = 2

        async def call(self, method: str, params: Any) -> Any:
            if method == "getTokenLargestAccounts" and self.misses:
                self.misses -= 1
                raise RpcError("getTokenLargestAccounts error: not a Token mint")
            return await super().call(method, params)

    rpc = Lagging([row("op_acct", 793_100_000)], {"op_acct": "OpWallet"})
    assert await asyncio.wait_for(
        sources.operator_ids_when_visible(rpc, MINT, POOL, pause_s=0), timeout=1
    ) == frozenset({"OpWallet", "FunderX"})

    never = Lagging([row("op_acct", 793_100_000)], {"op_acct": "OpWallet"})
    never.misses = 10**9
    with pytest.raises(TimeoutError):  # still unknown: the caller's timeout ends it
        await asyncio.wait_for(
            sources.operator_ids_when_visible(never, MINT, POOL, pause_s=0), timeout=0.05)
