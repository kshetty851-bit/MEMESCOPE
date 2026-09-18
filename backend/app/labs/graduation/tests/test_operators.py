"""Reading a coin's operator: its big wallets and the money behind them."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.labs.graduation import sources

MINT = "Bjsxb2QErbB4rhpSRsUgtNBPPri24R3AK58tQwjvpump"
POOL = "PoolAddress1111111111111111111111111111111"


class FakeRPC:
    def __init__(self, largest: list[dict[str, Any]] | None, owners: dict[str, str]) -> None:
        self.largest, self.owners, self.asked = largest, owners, []

    async def get_token_supply(self, mint: str) -> Decimal:
        return Decimal(1_000_000_000)

    async def call(self, method: str, params: Any) -> Any:
        self.asked.append(method)
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
