"""Pair admission is based on addresses, never symbols or the chain label."""

import base64

import httpx
import pytest

from app.labs.graduation import pool_sprint_pairs as pairs
from app.security.liquidity import POOL_DISCRIMINATOR, PUMPSWAP_PROGRAM, WSOL_MINT
from app.services.curve.pda import b58decode, b58encode


def account(quote=WSOL_MINT, owner=PUMPSWAP_PROGRAM):
    raw = bytearray(301)
    raw[:8] = POOL_DISCRIMINATOR
    for start in (11, 43, 75, 107, 139, 171):
        raw[start : start + 32] = bytes([start]) * 32
    raw[75:107] = b58decode(quote)
    return {"owner": owner, "data": [base64.b64encode(raw).decode(), "base64"]}


def test_decodes_actual_quote_and_rejects_wrong_owner_or_corrupt_data():
    assert pairs.account_identity(account())[1] == WSOL_MINT
    other = b58encode(bytes([4]) * 32)
    assert pairs.account_identity(account(other))[1] == other
    assert pairs.account_identity(account(owner="wrong")) is None
    assert pairs.account_identity({"owner": PUMPSWAP_PROGRAM, "data": ["bad"]}) is None
    assert pairs.account_identity(None) is None


@pytest.mark.asyncio
async def test_exact_pool_and_chain_required_and_symbols_do_not_prove_sol(monkeypatch):
    monkeypatch.setattr(pairs, "canonical_sol", lambda *a: False)
    monkeypatch.setattr(pairs.config, "rpc_url", lambda: "https://rpc.invalid")

    async def handle(request):
        if request.method == "POST":
            return httpx.Response(200, json={"result": {"value": [None, None]}})
        return httpx.Response(
            200,
            json={
                "pairs": [
                    {
                        "chainId": "solana",
                        "pairAddress": "other",
                        "baseToken": {"address": "coin"},
                        "quoteToken": {"address": WSOL_MINT},
                    },
                    {
                        "chainId": "ethereum",
                        "pairAddress": "unknown",
                        "baseToken": {"address": "coin"},
                        "quoteToken": {"address": WSOL_MINT},
                    },
                    {
                        "chainId": "solana",
                        "pairAddress": "spcx",
                        "baseToken": {"address": "coin"},
                        "quoteToken": {"address": "SPCX-address", "symbol": "SOL"},
                    },
                ]
            },
        )

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        pairs.httpx,
        "AsyncClient",
        lambda **kw: client_type(transport=httpx.MockTransport(handle), **kw),
    )
    out = await pairs.verify_pairs({"spcx": "coin", "unknown": "coin"})
    assert out == {"spcx": ("coin", "SPCX-address", "dexscreener_exact_pool")}
