"""Read-only pre-canary check: does a real Jupiter route pass our own barriers?

Assembles one live mainnet Jupiter order for a real wallet, decodes the returned
transaction, and runs it through exactly the checks the signer would run. It
**never signs and never submits**: the only network calls are a Jupiter quote, a
Jupiter swap assembly, and one `getGenesisHash`.

## Why this exists rather than a hardcoded verdict

`tx_inspect.DEFAULT_ALLOWED_PROGRAMS` was derived from one decoded mainnet route.
That is evidence, not a guarantee: Jupiter can route through a program we have
not seen, and the allowlist is fail-closed, so the first canary would refuse for
a reason nobody had anticipated. Running this against the real wallet and the
real mint *before* funding turns that surprise into a five-second answer.

A refusal here is the intended outcome of an unreviewed program, not a bug to
work around. Widen `REAL_WALLET_ALLOWED_PROGRAM_IDS` only after looking up what
the program actually is.

Usage (nothing here is enabled by running it):

    python -m scripts.validate_mainnet_order \\
        --taker <REAL_WALLET_PUBLIC_KEY> \\
        --output-mint <mint> \\
        --usdc-amount 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from decimal import Decimal

import httpx

from app.core.config import settings
from app.real_wallet.network import GENESIS_HASHES, rpc_host_allowed
from app.real_wallet.tx_inspect import DEFAULT_ALLOWED_PROGRAMS, inspect, verify

QUOTE_URL = "https://lite-api.jup.ag/swap/v1/quote"
SWAP_URL = "https://lite-api.jup.ag/swap/v1/swap"
USDC_DECIMALS = 6


def _allowed_programs() -> frozenset[str]:
    extra = {p.strip() for p in settings.REAL_WALLET_ALLOWED_PROGRAM_IDS if p.strip()}
    return DEFAULT_ALLOWED_PROGRAMS | extra


async def _check_rpc(rpc_url: str, network: str) -> dict[str, object]:
    """Prove the endpoint is one we allowed, and that it is the chain we expect."""
    if not rpc_host_allowed(rpc_url, allowlist=settings.REAL_WALLET_ALLOWED_RPC_HOSTS):
        return {"ok": False, "reason": "rpc_host_not_allowed", "url": rpc_url}
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            rpc_url,
            json={"jsonrpc": "2.0", "id": 1, "method": "getGenesisHash", "params": []},
        )
        observed = response.json().get("result")
    expected = GENESIS_HASHES.get(network)
    return {
        "ok": observed == expected,
        "expected_genesis_hash": expected,
        "observed_genesis_hash": observed,
    }


async def _assemble(taker: str, output_mint: str, amount_raw: int) -> str:
    """Quote, then assemble. Read-only: the result is an *unsigned* transaction."""
    async with httpx.AsyncClient(timeout=30) as client:
        quote = await client.get(
            QUOTE_URL,
            params={
                "inputMint": settings.JUPITER_USDC_MINT,
                "outputMint": output_mint,
                "amount": str(amount_raw),
            },
        )
        quote.raise_for_status()
        swap = await client.post(
            SWAP_URL,
            json={
                "quoteResponse": quote.json(),
                "userPublicKey": taker,
                "wrapAndUnwrapSol": True,
            },
        )
        swap.raise_for_status()
    transaction = swap.json().get("swapTransaction")
    if not isinstance(transaction, str) or not transaction:
        raise SystemExit("jupiter returned no transaction to inspect")
    return transaction


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--taker", required=True, help="The pinned wallet public key")
    parser.add_argument("--output-mint", required=True)
    parser.add_argument("--usdc-amount", default="5")
    parser.add_argument("--rpc-url", default=settings.REAL_WALLET_RPC_URL)
    parser.add_argument("--network", default=settings.REAL_WALLET_NETWORK)
    args = parser.parse_args()

    amount_raw = int(Decimal(args.usdc_amount).scaleb(USDC_DECIMALS))
    transaction = await _assemble(args.taker, args.output_mint, amount_raw)
    facts = inspect(transaction)
    verdict = verify(
        encoded_transaction=transaction,
        expected_fee_payer=args.taker,
        allowed_programs=_allowed_programs(),
    )
    report = {
        "signed": False,
        "submitted": False,
        "rpc": await _check_rpc(args.rpc_url, args.network),
        "fee_payer": facts.fee_payer,
        "required_signatures": facts.required_signatures,
        "program_ids": list(facts.program_ids),
        "program_from_lookup_table": facts.program_from_lookup_table,
        "lookup_tables": list(facts.lookup_tables),
        "message_fingerprint": facts.message_fingerprint,
        "would_be_signed": verdict.approved,
        "refusal_reasons": list(verdict.reason_codes),
        "unlisted_programs": sorted(set(facts.program_ids) - _allowed_programs()),
    }
    print(json.dumps(report, indent=2))
    return 0 if verdict.approved and report["rpc"].get("ok") else 1  # type: ignore[union-attr]


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
