"""A SOL-paid swap has to be measurable, or its position is never recorded.

The wallet holds native SOL and the driver buys with it, but settlement only
read token balances. Jupiter wraps native SOL into a temporary account that is
opened and closed inside the same transaction, so the SOL side appears in
neither token list: every SOL-paid buy settled as UNKNOWN, its tokens were
never recorded, and nothing ever sold them.

The fixtures are two real pump-amm swaps from mainnet (a 0.03 SOL buy and the
matching sell), cut down to what settlement reads, with every address
replaced. The buy is the useful one: it opens the token account in the same
transaction, so rent moves out of the wallet's lamports as well as the swap.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from app.core.config import settings
from app.real_wallet.reconciliation import (
    ChainOutcome,
    SolanaRpcTransactionReconciler,
    extract_leg_delta,
    extract_wallet_sol_delta,
    extract_wallet_token_delta,
)

pytestmark = pytest.mark.unit

SWAPS = json.loads((Path(__file__).parent / "fixtures" / "real_wallet_sol_swaps.json")
                   .read_text())
WALLET = SWAPS["wallet"]
TOKEN = SWAPS["token"]
SOL = settings.EXECUTION_SOL_MINT
ENCODINGS = ("jsonParsed", "json")

#: 0.03 SOL plus pump-amm's 0.25% — the swap alone, without the 105,000
#: lamport network fee or the 1,513,840 lamports of token-account rent.
BUY_SPENT = 30_075_000
SELL_RECEIVED = 29_185_068
TOKENS = 1_640_115_442_951


def _tx(side: str, encoding: str) -> dict[str, Any]:
    return copy.deepcopy(SWAPS[side][encoding])


@pytest.mark.parametrize("encoding", ENCODINGS)
def test_a_buy_measures_the_swap_not_the_fee_or_the_rent(encoding):
    tx = _tx("buy", encoding)
    meta = tx["meta"]
    # What a naive reading of the wallet's own lamports would claim.
    assert meta["postBalances"][0] - meta["preBalances"][0] == -31_693_840

    sol = extract_wallet_sol_delta(transaction=tx, wallet_public_key=WALLET)
    assert sol is not None
    assert (sol.mint, sol.raw_delta, sol.decimals) == (SOL, -BUY_SPENT, 9)
    token = extract_leg_delta(transaction=tx, wallet_public_key=WALLET, mint=TOKEN)
    assert token is not None
    assert (token.raw_delta, token.decimals) == (TOKENS, 6)


@pytest.mark.parametrize("encoding", ENCODINGS)
def test_a_sell_measures_what_came_back(encoding):
    tx = _tx("sell", encoding)
    sol = extract_leg_delta(transaction=tx, wallet_public_key=WALLET, mint=SOL)
    assert sol is not None and sol.raw_delta == SELL_RECEIVED
    token = extract_leg_delta(transaction=tx, wallet_public_key=WALLET, mint=TOKEN)
    assert token is not None and token.raw_delta == -TOKENS


def test_the_token_rows_alone_never_saw_the_sol_side():
    """Why every SOL-paid buy used to stay UNKNOWN."""
    for side in ("buy", "sell"):
        assert extract_wallet_token_delta(
            transaction=_tx(side, "jsonParsed"), wallet_public_key=WALLET, mint=SOL
        ) is None


def test_the_fee_is_added_back_only_when_the_wallet_paid_it():
    tx = _tx("sell", "json")
    keys = tx["transaction"]["message"]["accountKeys"]
    assert keys[0] == WALLET
    # Someone else pays: the wallet's balance change is the swap alone.
    for field in ("preBalances", "postBalances"):
        balances = tx["meta"][field]
        balances[0], balances[1] = balances[1], balances[0]
    keys[0], keys[1] = keys[1], keys[0]
    for field in ("preTokenBalances", "postTokenBalances"):
        for row in tx["meta"][field]:
            row["accountIndex"] = {0: 1, 1: 0}.get(row["accountIndex"],
                                                   row["accountIndex"])
    sol = extract_wallet_sol_delta(transaction=tx, wallet_public_key=WALLET)
    assert sol is not None and sol.raw_delta == SELL_RECEIVED - tx["meta"]["fee"]


def test_an_unreadable_transaction_is_unknown_not_zero():
    short = _tx("buy", "jsonParsed")
    short["meta"]["postBalances"].pop()
    assert extract_wallet_sol_delta(transaction=short, wallet_public_key=WALLET) is None
    json_without_lookups = _tx("buy", "json")
    del json_without_lookups["meta"]["loadedAddresses"]
    assert extract_wallet_sol_delta(transaction=json_without_lookups,
                                    wallet_public_key=WALLET) is None
    assert extract_wallet_sol_delta(transaction=_tx("buy", "json"),
                                    wallet_public_key="SomeoneElse") is None


class _Rpc:
    def __init__(self, tx: dict[str, Any]) -> None:
        self._tx = tx

    async def get_transaction(self, signature: str, *, attempts: int | None = None):
        del signature, attempts
        return self._tx


def _intent(input_mint: str, output_mint: str) -> Any:
    return type("Intent", (), {"transaction_signature": "sig", "wallet_public_key": WALLET,
                               "input_mint": input_mint, "output_mint": output_mint})()


async def test_a_sol_paid_buy_is_confirmed_with_both_legs():
    receipt = await SolanaRpcTransactionReconciler(
        _Rpc(_tx("buy", "jsonParsed"))  # type: ignore[arg-type]
    ).inspect(_intent(SOL, TOKEN))
    assert receipt.outcome is ChainOutcome.CONFIRMED
    assert receipt.has_settlement_evidence
    assert (receipt.actual_input_amount, receipt.actual_input_decimals) == (str(BUY_SPENT), 9)
    assert (receipt.actual_output_amount, receipt.actual_output_decimals) == (str(TOKENS), 6)
    assert receipt.network_fee_lamports == 105_000


async def test_a_sell_back_into_sol_is_confirmed_with_both_legs():
    receipt = await SolanaRpcTransactionReconciler(
        _Rpc(_tx("sell", "jsonParsed"))  # type: ignore[arg-type]
    ).inspect(_intent(TOKEN, SOL))
    assert receipt.outcome is ChainOutcome.CONFIRMED
    assert receipt.actual_input_amount == str(TOKENS)
    assert receipt.actual_output_amount == str(SELL_RECEIVED)
