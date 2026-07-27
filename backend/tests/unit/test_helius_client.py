"""Unit tests for the Helius client's retry behaviour, using a mock transport."""

from __future__ import annotations

import httpx
import pytest

from app.services.helius.client import HeliusClient, HeliusError
from app.services.scanner.backoff import BackoffPolicy

pytestmark = pytest.mark.unit

# Zero delays keep the retry tests fast.
NO_WAIT = BackoffPolicy(initial_seconds=0.0, max_seconds=0.0, multiplier=1.0, jitter=False)


def _client(handler: httpx.MockTransport) -> HeliusClient:
    return HeliusClient(
        rpc_url="https://rpc.test",
        client=httpx.AsyncClient(transport=handler),
        backoff=NO_WAIT,
    )


async def test_successful_call_returns_result() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"jsonrpc": "2.0", "result": {"ok": True}})
    )
    assert await _client(transport).call("getSlot", []) == {"ok": True}


async def test_transient_500_is_retried_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(500)
        return httpx.Response(200, json={"result": "recovered"})

    assert await _client(httpx.MockTransport(handler)).call("m", [], attempts=4) == "recovered"
    assert calls["n"] == 3


async def test_rate_limit_is_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return (
            httpx.Response(429) if calls["n"] == 1 else httpx.Response(200, json={"result": 1})
        )

    assert await _client(httpx.MockTransport(handler)).call("m", [], attempts=3) == 1


async def test_network_error_is_retried_then_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(HeliusError, match="failed after 3 attempts"):
        await _client(httpx.MockTransport(handler)).call("m", [], attempts=3)


async def test_json_rpc_application_error_is_not_retried() -> None:
    """A well-formed error response will fail identically on every retry."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"error": {"code": -32602, "message": "bad params"}})

    with pytest.raises(HeliusError):
        await _client(httpx.MockTransport(handler)).call("m", [], attempts=3)
    assert calls["n"] == 1


async def test_get_transaction_polls_until_available() -> None:
    """A confirmed transaction is not instantly queryable."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(200, json={"result": None})
        return httpx.Response(200, json={"result": {"slot": 1}})

    result = await _client(httpx.MockTransport(handler)).get_transaction("sig", attempts=5)
    assert result == {"slot": 1}


async def test_get_transaction_gives_up_and_returns_none() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"result": None}))
    assert await _client(transport).get_transaction("sig", attempts=2) is None


async def test_get_asset_ignores_partial_response_without_content() -> None:
    """A freshly indexed asset can return a body with no content yet."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json={"result": {"id": "x"}})
        return httpx.Response(200, json={"result": {"id": "x", "content": {"metadata": {}}}})

    result = await _client(httpx.MockTransport(handler)).get_asset("mint", attempts=3)
    assert result is not None
    assert "content" in result


async def test_get_asset_returns_none_when_never_indexed() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"result": None}))
    assert await _client(transport).get_asset("mint", attempts=2) is None


async def test_unstarted_client_raises_clearly() -> None:
    with pytest.raises(HeliusError, match="not started"):
        await HeliusClient(rpc_url="https://rpc.test").call("m", [])
