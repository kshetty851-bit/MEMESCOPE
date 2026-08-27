"""Plain Solana JSON-RPC. Works against any compliant node.

This is the implementation that removes the hard vendor dependency: a public
endpoint, a self-hosted validator, or any paid provider's standard URL all
speak this and nothing else. Every method is in the core Solana RPC API —
`getTransaction`, `getMultipleAccounts` — with no indexer extension anywhere in
the path.

The retry policy is the interesting part and it was already right: transport
failures, 5xx and 429 are retried with backoff, while a well-formed JSON-RPC
*application* error is not, because it will fail identically every time. That
distinction is preserved here unchanged — it came out of the scanner's first
live run, and it is the difference between waiting out a rate limit and hammering
a node about a transaction that does not exist.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

from decimal import Decimal

import httpx

from app.core.backoff import BackoffPolicy
from app.core.config import settings
from app.core.logging import get_logger
from app.services.rpc.base import (
    RpcExhaustedError,
    RpcMethodRestrictedError,
    RpcDescription,
    RpcError,
    RpcRateLimitError,
    SolanaRPC,
)

logger = get_logger(__name__)

#: `getMultipleAccounts` accepts at most 100 addresses per request. Published
#: here rather than in the collector: it is a property of the RPC, not of what
#: happens to be reading accounts this week.
MAX_ACCOUNTS_PER_CALL = 100

#: Why a plain node cannot answer the metadata read. Names the cause, so an
#: operator reads "this endpoint does not index" rather than "no name found".
NO_DAS_REASON = (
    "This endpoint serves standard Solana JSON-RPC and does not index the "
    "Digital Asset Standard, so token metadata cannot be read from it. Names "
    "and symbols stay unresolved until a DAS-capable endpoint or a Metaplex "
    "metadata reader is configured."
)


class StandardSolanaRPC(SolanaRPC):
    """Any Solana node that speaks the standard JSON-RPC API."""

    name: ClassVar[str] = "solana"
    supports_metadata: ClassVar[bool] = False
    metadata_unavailable_reason: ClassVar[str | None] = NO_DAS_REASON

    def __init__(
        self,
        *,
        rpc_url: str | None = None,
        client: httpx.AsyncClient | None = None,
        backoff: BackoffPolicy | None = None,
    ) -> None:
        self._rpc_url = rpc_url or settings.SOLANA_RPC_URL
        self._client = client
        # An injected client is borrowed, never owned: closing someone else's
        # connection pool is how one caller's teardown breaks another's.
        self._owns_client = client is None
        self._backoff = backoff or BackoffPolicy.from_settings()

    # --- Lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(settings.SOLANA_RPC_TIMEOUT_SECONDS),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
            self._owns_client = True

    async def close(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    def describe(self) -> RpcDescription:
        return RpcDescription(
            name=self.name,
            # Redacted: an RPC URL routinely carries an API key in its query
            # string, and `describe()` reaches logs and the health surface.
            endpoint=_redact(self._rpc_url),
            supports_metadata=self.supports_metadata,
            metadata_unavailable_reason=self.metadata_unavailable_reason,
        )

    @property
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RpcError(
                f"{type(self).__name__} is not started. "
                "Call start() or use it as a context manager."
            )
        return self._client

    # --- Calls ---------------------------------------------------------------

    async def call(self, method: str, params: Any, *, attempts: int = 3) -> Any:
        """Issue a JSON-RPC call, retrying transport and 5xx/429 failures.

        A JSON-RPC *application* error (a well-formed error response) is not
        retried — it will fail identically every time.
        """
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = await self._http.post(self._rpc_url, json=payload)

                if response.status_code == 429:
                    last_error = RpcRateLimitError(f"{method} rate limited")
                elif response.status_code in (403, 404, 405):
                    # A capability refusal, not weather: retrying is waste and
                    # the message must never carry the URL httpx puts in it.
                    raise RpcMethodRestrictedError(
                        f"{method} refused by {self.name} "
                        f"(HTTP {response.status_code}; plan/method restriction)"
                    )
                elif response.status_code >= 500:
                    last_error = RpcError(f"{method} returned {response.status_code}")
                else:
                    response.raise_for_status()
                    body = response.json()
                    if isinstance(body, dict) and body.get("error"):
                        raise RpcError(f"{method} error: {body['error']}")
                    return body.get("result") if isinstance(body, dict) else None

            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = RpcError(
                    f"{type(exc).__name__}: "
                    + str(exc).replace(self._rpc_url, _redact(self._rpc_url))
                )
            except ValueError as exc:  # malformed JSON body
                last_error = RpcError(f"{method} returned invalid JSON: {exc}")

            if attempt < attempts:
                delay = self._backoff.delay_for(attempt)
                logger.warning(
                    "rpc_call_retry",
                    provider=self.name,
                    method=method,
                    attempt=attempt,
                    delay_seconds=round(delay, 2),
                    error=str(last_error),
                )
                await asyncio.sleep(delay)

        if isinstance(last_error, RpcRateLimitError):
            raise RpcRateLimitError(
                f"{method} failed after {attempts} attempts: {last_error}"
            )
        raise RpcExhaustedError(f"{method} failed after {attempts} attempts: {last_error}")

    async def get_transaction(
        self, signature: str, *, attempts: int | None = None
    ) -> dict[str, Any] | None:
        """Fetch a parsed transaction, polling while it is still propagating.

        Returns None when the transaction never became available — the caller
        decides whether that is worth recording.
        """
        total = attempts or settings.SCANNER_TX_FETCH_ATTEMPTS
        params = [
            signature,
            {
                "encoding": "jsonParsed",
                "maxSupportedTransactionVersion": 0,
                "commitment": settings.SCANNER_COMMITMENT,
            },
        ]

        for attempt in range(1, total + 1):
            try:
                result = await self.call("getTransaction", params, attempts=2)
            except RpcError as exc:
                logger.warning(
                    "rpc_get_transaction_failed", signature=signature, error=str(exc)
                )
                result = None

            if isinstance(result, dict):
                return result

            if attempt < total:
                await asyncio.sleep(self._backoff.delay_for(attempt))

        logger.warning("rpc_transaction_unavailable", signature=signature, attempts=total)
        return None

    async def get_multiple_accounts(
        self, addresses: list[str], *, encoding: str = "base64"
    ) -> list[dict[str, Any] | None]:
        """One batched account read, positionally aligned with `addresses`.

        Raises rather than returning a short list when the call fails: a caller
        pairing accounts back to mints by position must be able to tell "this
        account does not exist" from "this read did not happen", and a truncated
        list silently conflates them.
        """
        if not addresses:
            return []
        if len(addresses) > MAX_ACCOUNTS_PER_CALL:
            raise RpcError(
                f"getMultipleAccounts accepts at most {MAX_ACCOUNTS_PER_CALL} "
                f"addresses; {len(addresses)} were given. Chunk before calling."
            )

        response = await self.call("getMultipleAccounts", [addresses, {"encoding": encoding}])
        values = (response or {}).get("value")
        if not isinstance(values, list):
            raise RpcError("getMultipleAccounts returned no value array")
        return list(values)


    async def get_token_supply(self, mint_address: str) -> Decimal | None:
        """`getTokenSupply`, returned in whole tokens rather than base units.

        Unreadable is `None` rather than an exception: a concentration check is
        one input among several, and an RPC hiccup should make the caller refuse
        the trade, not crash the evaluation that would have refused it anyway.
        """
        try:
            response = await self.call("getTokenSupply", [mint_address])
        except RpcError:
            return None
        value = (response or {}).get("value") or {}
        raw, decimals = value.get("amount"), value.get("decimals")
        if raw is None or decimals is None:
            return None
        try:
            supply = Decimal(str(raw)) / (Decimal(10) ** int(decimals))
        except (ArithmeticError, ValueError):
            return None
        # A zero or negative supply is not a real mint; treat it as unreadable
        # so a caller cannot divide by it.
        return supply if supply > 0 else None


def _redact(url: str) -> str:
    """The endpoint with every place a credential can live masked.

    Keys arrive as query strings (Helius) AND as path segments (Chainstack
    embeds the access token directly in the path) — measured live when an
    httpx 403 message printed a full Chainstack URL into worker logs. Host
    survives; nothing after it does.
    """
    if not url:
        return ""
    base = url.split("?", 1)[0]
    parts = base.split("/", 3)
    return "/".join(parts[:3]) + ("/***" if len(parts) > 3 and parts[3] else "")
