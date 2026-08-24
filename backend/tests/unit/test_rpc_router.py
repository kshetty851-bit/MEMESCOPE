"""The router's promises: failover on transient, never on deterministic,
never to the public node, breaker learns, provenance tells the truth."""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.rpc import router as router_module
from app.services.rpc.base import RpcError, RpcExhaustedError, RpcRateLimitError
from app.services.rpc.router import FallbackRPC, _BREAKERS

pytestmark = pytest.mark.unit


class _Stub:
    def __init__(self, name, outcomes):
        self.name = name
        self.outcomes = list(outcomes)
        self.calls = 0

    async def start(self): ...
    async def close(self): ...

    async def call(self, method, params, *, attempts=2):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture(autouse=True)
def _fresh_breakers(monkeypatch):
    _BREAKERS.clear()
    monkeypatch.setattr(settings, "CHAINSTACK_RPC_URL", "https://example.invalid/t")
    monkeypatch.setattr(settings, "HELIUS_API_KEY", "test-key")
    yield
    _BREAKERS.clear()


def _router(primary, secondary):
    r = FallbackRPC.__new__(FallbackRPC)
    r._providers = [primary, secondary]
    r.last_provider = None
    r.last_latency_ms = None
    r.last_fallback_used = False
    return r


async def test_rate_limit_fails_over_and_provenance_says_so():
    primary = _Stub("chainstack", [RpcRateLimitError("429")])
    secondary = _Stub("helius", [{"ok": 1}])
    r = _router(primary, secondary)
    assert await r.call("getTokenSupply", []) == {"ok": 1}
    assert r.last_provider == "helius"
    assert r.last_fallback_used is True
    assert r.last_latency_ms is not None


async def test_deterministic_error_never_fails_over():
    primary = _Stub("chainstack", [RpcError("getFoo error: Invalid param")])
    secondary = _Stub("helius", [{"never": True}])
    r = _router(primary, secondary)
    with pytest.raises(RpcError):
        await r.call("getFoo", [])
    assert secondary.calls == 0  # a bad request is bad on every node


async def test_both_transient_raises_exhausted_not_public_fallback():
    r = _router(_Stub("chainstack", [RpcExhaustedError("x")]),
                _Stub("helius", [RpcRateLimitError("y")]))
    with pytest.raises(RpcExhaustedError):
        await r.call("getTokenLargestAccounts", [])
    # No third provider exists to try: the public node is not in the chain.


async def test_breaker_opens_after_threshold_and_skips_provider():
    primary = _Stub("chainstack", [RpcExhaustedError("1"), RpcExhaustedError("2"),
                                   RpcExhaustedError("3"), {"never": True}])
    secondary = _Stub("helius", [{"a": 1}, {"b": 2}, {"c": 3}, {"d": 4}])
    r = _router(primary, secondary)
    for _ in range(3):
        await r.call("m", [])
    assert _BREAKERS["chainstack"].is_open
    await r.call("m", [])
    assert primary.calls == 3  # the fourth call never touched the open primary
    assert r.last_provider == "helius"


async def test_unconfigured_router_refuses_loudly():
    r = FallbackRPC.__new__(FallbackRPC)
    r._providers = []
    with pytest.raises(RpcError, match="public endpoint is diagnostics-only"):
        await r.call("getHealth", [])


def test_chainstack_requires_its_endpoint(monkeypatch):
    from app.services.rpc.chainstack import ChainstackRPC

    monkeypatch.setattr(settings, "CHAINSTACK_RPC_URL", "")
    with pytest.raises(RpcError, match="CHAINSTACK_RPC_URL"):
        ChainstackRPC()
