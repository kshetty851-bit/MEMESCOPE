"""The RPC abstraction, and what each implementation honestly claims.

Sprint 13's point was not a new client — it was making the vendor surface
*visible and optional*. So what is asserted here is mostly about declarations:
which node can answer what, and what it says when it cannot.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.core.backoff import BackoffPolicy
from app.services.helius.client import HeliusClient, HeliusError
from app.services.rpc import RpcError, SolanaRPC, available_rpcs, get_rpc
from app.services.rpc.helius import HeliusRPC
from app.services.rpc.standard import (
    MAX_ACCOUNTS_PER_CALL,
    NO_DAS_REASON,
    StandardSolanaRPC,
)

pytestmark = pytest.mark.unit

FAST = BackoffPolicy(initial_seconds=0, max_seconds=0, jitter=False)


def _client(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _ok(result: Any) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    return handler


class TestContract:
    def test_both_implementations_satisfy_the_interface(self) -> None:
        assert issubclass(StandardSolanaRPC, SolanaRPC)
        assert issubclass(HeliusRPC, SolanaRPC)

    def test_helius_is_one_implementation_among_others(self) -> None:
        """The registry knows concrete classes; nothing else has to."""
        assert set(available_rpcs()) >= {"solana", "helius"}

    def test_the_configured_provider_is_what_you_get(self) -> None:
        assert isinstance(get_rpc("solana"), StandardSolanaRPC)
        assert isinstance(get_rpc("helius"), HeliusRPC)

    def test_an_unknown_provider_falls_back_to_the_neutral_one(self) -> None:
        """A typo must not silently route traffic to a vendor nobody asked for,
        and must not take the platform down either."""
        assert type(get_rpc("nonesuch")) is StandardSolanaRPC


class TestMetadataCapability:
    def test_a_standard_node_declares_that_it_cannot_index(self) -> None:
        """DAS is served by indexers, not validators. Declared rather than
        discovered by getting nothing back."""
        rpc = StandardSolanaRPC(rpc_url="https://example.invalid")

        assert rpc.supports_metadata is False
        assert rpc.metadata_unavailable_reason == NO_DAS_REASON
        assert rpc.describe().supports_metadata is False

    def test_helius_declares_that_it_can(self) -> None:
        rpc = HeliusRPC(rpc_url="https://example.invalid")

        assert rpc.supports_metadata is True
        assert rpc.metadata_unavailable_reason is None

    async def test_a_standard_node_returns_none_rather_than_failing(self) -> None:
        """The scanner already treats `None` as unresolved-so-far. A node that
        never had metadata is not an error, and raising here would take
        discovery down on an endpoint that can serve everything else.
        """
        async with StandardSolanaRPC(
            rpc_url="https://example.invalid", client=_client(_ok(None))
        ) as rpc:
            assert await rpc.get_asset("mint") is None

    def test_describe_never_leaks_the_key(self) -> None:
        """`describe()` reaches logs and the health surface, and an RPC URL
        routinely carries an API key in its query string."""
        rpc = StandardSolanaRPC(rpc_url="https://node.example/?api-key=secret-value")

        assert "secret-value" not in rpc.describe().endpoint


class TestStandardCalls:
    async def test_it_returns_the_jsonrpc_result(self) -> None:
        async with StandardSolanaRPC(
            rpc_url="https://example.invalid", client=_client(_ok({"ok": True}))
        ) as rpc:
            assert await rpc.call("getSlot", []) == {"ok": True}

    async def test_an_application_error_is_not_retried(self) -> None:
        """It will fail identically every time. Retrying a well-formed error is
        how a node gets hammered about a transaction that does not exist."""
        seen: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(1)
            return httpx.Response(
                200, json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32602}}
            )

        async with StandardSolanaRPC(
            rpc_url="https://example.invalid", client=_client(handler), backoff=FAST
        ) as rpc:
            with pytest.raises(RpcError):
                await rpc.call("getSlot", [], attempts=3)

        assert len(seen) == 1

    async def test_a_rate_limit_is_retried_then_reported(self) -> None:
        attempts: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            attempts.append(1)
            return httpx.Response(429)

        async with StandardSolanaRPC(
            rpc_url="https://example.invalid", client=_client(handler), backoff=FAST
        ) as rpc:
            with pytest.raises(RpcError):
                await rpc.call("getSlot", [], attempts=3)

        assert len(attempts) == 3

    async def test_an_unstarted_client_says_so(self) -> None:
        rpc = StandardSolanaRPC(rpc_url="https://example.invalid")

        with pytest.raises(RpcError, match="not started"):
            await rpc.call("getSlot", [])

    async def test_an_injected_client_is_borrowed_not_owned(self) -> None:
        """Closing someone else's connection pool is how one caller's teardown
        breaks another's — the bug the collector's lifecycle test records."""
        client = _client(_ok(None))
        rpc = StandardSolanaRPC(rpc_url="https://example.invalid", client=client)

        await rpc.start()
        await rpc.close()

        assert not client.is_closed
        await client.aclose()


class TestAccountReads:
    async def test_accounts_come_back_positionally(self) -> None:
        payload = {"value": [{"data": ["AA==", "base64"]}, None]}

        async with StandardSolanaRPC(
            rpc_url="https://example.invalid", client=_client(_ok(payload))
        ) as rpc:
            values = await rpc.get_multiple_accounts(["a", "b"])

        assert len(values) == 2
        assert values[1] is None

    async def test_an_empty_request_asks_nothing(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("no call should be made")

        async with StandardSolanaRPC(
            rpc_url="https://example.invalid", client=_client(handler)
        ) as rpc:
            assert await rpc.get_multiple_accounts([]) == []

    async def test_over_the_chunk_limit_is_refused_at_the_boundary(self) -> None:
        """The limit belongs to the RPC, not to whatever is reading accounts
        this week — and a silent truncation would lose tokens without a trace.
        """
        async with StandardSolanaRPC(
            rpc_url="https://example.invalid", client=_client(_ok({"value": []}))
        ) as rpc:
            with pytest.raises(RpcError, match="at most 100"):
                await rpc.get_multiple_accounts(["x"] * (MAX_ACCOUNTS_PER_CALL + 1))

    async def test_a_missing_value_array_raises_rather_than_reading_as_absent(
        self,
    ) -> None:
        """"This account does not exist" and "this read did not happen" must
        stay distinguishable — the caller pairs results back to mints by
        position."""
        async with StandardSolanaRPC(
            rpc_url="https://example.invalid", client=_client(_ok({}))
        ) as rpc:
            with pytest.raises(RpcError):
                await rpc.get_multiple_accounts(["a"])


class TestCompatibility:
    def test_the_old_names_still_resolve(self) -> None:
        """Pre-abstraction imports keep working, so the move is one reviewable
        change rather than a rename across a dozen call sites."""
        assert HeliusClient is HeliusRPC
        assert HeliusError is RpcError
