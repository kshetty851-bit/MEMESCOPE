"""The RPC router: Chainstack primary, Helius fallback, public never.

    standard call -> chainstack
                     └─ eligible transient failure -> helius (if configured)
                          └─ both unhealthy -> unavailable

Eligible means the request might succeed elsewhere: rate limits, timeouts,
transient 5xx, transport failures, or a provider whose breaker is open.
A deterministic JSON-RPC application error (bad account, malformed request,
unsupported method) fails identically on every node and is raised immediately
— retrying it across providers would be a retry storm with extra steps.

The public Solana endpoint is deliberately NOT in this chain. It is a
diagnostics tool an operator points at by name (`get_rpc("solana")`), never a
silent production dependency: its aggressive per-method limits are how holder
collection produced 60 failure rows and one datum.

Each provider carries a small circuit breaker (consecutive transient failures
open it for a cooldown), so a dead provider costs one skipped glance per call
rather than a timeout each. Provenance is first-class: after every successful
`call`, `last_provider`, `last_latency_ms` and `last_fallback_used` describe
exactly where the answer came from, so research rows can say so.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any, ClassVar

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.services.rpc.base import (
    RpcDescription,
    RpcError,
    RpcExhaustedError,
    RpcMethodRestrictedError,
    RpcRateLimitError,
    SolanaRPC,
)

logger = get_logger(__name__)

#: Failures in a row before a provider's breaker opens.
BREAKER_THRESHOLD = 3
#: How long an open breaker skips its provider.
BREAKER_COOLDOWN_SECONDS = 60.0

#: Errors that justify trying the next provider.
TRANSIENT = (RpcRateLimitError, RpcExhaustedError, httpx.TransportError, TimeoutError)


class _Breaker:
    __slots__ = ("failures", "open_until")

    def __init__(self) -> None:
        self.failures = 0
        self.open_until = 0.0

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= BREAKER_THRESHOLD:
            self.open_until = time.monotonic() + BREAKER_COOLDOWN_SECONDS

    def record_success(self) -> None:
        self.failures = 0
        self.open_until = 0.0

    @property
    def is_open(self) -> bool:
        return time.monotonic() < self.open_until


#: (provider, method) pairs a provider has refused outright (403/404/405).
#: A plan gap is stable for the life of the process — skipping the refusing
#: provider saves a wasted round trip per call, and a plan upgrade is a
#: deploy/restart anyway.
_RESTRICTED: set[tuple[str, str]] = set()

#: Module-level breaker state, keyed by provider name. Shared across router
#: instances within one process on purpose: ten collectors should learn from
#: one provider outage once, not ten times.
_BREAKERS: dict[str, _Breaker] = {}


class FallbackRPC(SolanaRPC):
    """Chainstack-primary standard RPC with explicit, bounded failover."""

    name: ClassVar[str] = "auto"

    def __init__(self) -> None:
        # Imported here, not at module top: registry imports this module.
        from app.services.rpc.helius import HeliusRPC

        from app.services.rpc.chainstack import ChainstackRPC

        self._providers: list[SolanaRPC] = []
        if settings.CHAINSTACK_RPC_URL:
            self._providers.append(ChainstackRPC())
        if settings.HELIUS_API_KEY:
            self._providers.append(HeliusRPC())
        self.last_provider: str | None = None
        self.last_latency_ms: int | None = None
        self.last_fallback_used: bool = False

    # --- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        for provider in self._providers:
            await provider.start()

    async def close(self) -> None:
        for provider in self._providers:
            await provider.close()

    def describe(self) -> RpcDescription:
        chain = " -> ".join(p.name for p in self._providers) or "none configured"
        return RpcDescription(
            name=self.name,
            endpoint=f"router({chain})",
            supports_metadata=False,
            metadata_unavailable_reason="router serves standard JSON-RPC only",
        )

    # --- the call ------------------------------------------------------------

    async def call(self, method: str, params: Any, *, attempts: int = 2) -> Any:
        if not self._providers:
            raise RpcError(
                "No production RPC configured: set CHAINSTACK_RPC_URL (primary) "
                "and/or HELIUS_API_KEY (fallback). The public endpoint is "
                "diagnostics-only and is never used implicitly."
            )
        last_transient: Exception | None = None
        for index, provider in enumerate(self._providers):
            if (provider.name, method) in _RESTRICTED:
                last_transient = last_transient or RpcMethodRestrictedError(
                    f"{method} restricted on {provider.name}"
                )
                continue
            breaker = _BREAKERS.setdefault(provider.name, _Breaker())
            if breaker.is_open:
                last_transient = last_transient or RpcError(
                    f"{provider.name} circuit open"
                )
                continue
            started = time.perf_counter()
            try:
                result = await provider.call(method, params, attempts=attempts)
            except RpcMethodRestrictedError as exc:
                # Capability gap, not unhealth: remember it, skip the breaker,
                # let the next provider answer.
                _RESTRICTED.add((provider.name, method))
                last_transient = exc
                logger.warning(
                    "rpc_method_restricted",
                    method=method,
                    provider=provider.name,
                )
                continue
            except TRANSIENT as exc:
                breaker.record_failure()
                last_transient = exc
                logger.warning(
                    "rpc_router_failover",
                    method=method,
                    provider=provider.name,
                    error=type(exc).__name__,
                    breaker_failures=breaker.failures,
                )
                continue
            # Deterministic RpcError propagates from here untouched: it counts
            # neither for the breaker nor as a reason to bother the next node.
            breaker.record_success()
            self.last_provider = provider.name
            self.last_latency_ms = int((time.perf_counter() - started) * 1000)
            self.last_fallback_used = index > 0
            return result
        raise RpcExhaustedError(
            f"{method}: every configured provider refused transiently "
            f"({last_transient})"
        )

    # --- interface delegates, all riding the routed call ---------------------

    async def get_transaction(
        self, signature: str, *, attempts: int | None = None
    ) -> dict[str, Any] | None:
        return await self.call(
            "getTransaction",
            [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
            attempts=attempts or 2,
        )

    async def get_token_supply(self, mint_address: str) -> Decimal | None:
        """Route the supply read through the same failover the rest uses.

        Without this the router inherited the abstract base's `None`, which
        means "unreadable" — and the concentration cap treats unreadable as a
        REFUSAL, so every token failed the safety gate for a fact nobody could
        measure. Fail-closed, so nothing unsafe shipped, but nothing tradeable
        either: a default that silently disables a check is worse than no check,
        because it looks like the check is running.
        """
        try:
            response = await self.call("getTokenSupply", [mint_address])
        except RpcError:
            return None
        value = (response or {}).get("value") if isinstance(response, dict) else None
        if not isinstance(value, dict):
            return None
        raw, decimals = value.get("amount"), value.get("decimals")
        if raw is None or decimals is None:
            return None
        try:
            supply = Decimal(str(raw)) / (Decimal(10) ** int(decimals))
        except (ArithmeticError, ValueError):
            return None
        return supply if supply > 0 else None

    async def get_multiple_accounts(
        self, addresses: list[str], *, encoding: str = "base64"
    ) -> list[dict[str, Any] | None]:
        result = await self.call(
            "getMultipleAccounts", [addresses, {"encoding": encoding}]
        )
        value = (result or {}).get("value") if isinstance(result, dict) else None
        return value if isinstance(value, list) else [None] * len(addresses)
