"""The public node's backup (2026-10-21): asked only after the public one refuses."""

from __future__ import annotations

import httpx
import pytest

from app.core.backoff import BackoffPolicy
from app.services.rpc.standard import PUBLIC_SOLANA_RPC, StandardSolanaRPC

pytestmark = pytest.mark.unit
BACKUP = "https://solana-rpc.publicnode.com"


def _client(seen: list[str]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url).rstrip("/"))
        if str(request.url).startswith(PUBLIC_SOLANA_RPC):
            return httpx.Response(413, text="Request Entity Too Large")
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"value": 7}})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_a_refusal_from_the_public_node_is_answered_by_the_backup() -> None:
    seen: list[str] = []
    rpc = StandardSolanaRPC(rpc_url=PUBLIC_SOLANA_RPC, client=_client(seen),
                            backoff=BackoffPolicy(initial_seconds=0, max_seconds=0, jitter=False))
    assert await rpc.call("getBalance", ["x"]) == {"value": 7}
    assert seen == [PUBLIC_SOLANA_RPC, BACKUP]


async def test_a_keyed_vendor_url_never_falls_back_to_a_public_node() -> None:
    seen: list[str] = []
    rpc = StandardSolanaRPC(rpc_url="https://vendor.example/KEY", client=_client(seen),
                            backoff=BackoffPolicy(initial_seconds=0, max_seconds=0, jitter=False))
    assert await rpc.call("getBalance", ["x"]) == {"value": 7}
    assert seen == ["https://vendor.example/KEY"]
