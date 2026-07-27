"""Helius JSON-RPC client.

Wraps the two calls the scanner needs — `getTransaction` and DAS `getAsset` —
with retry and exponential backoff. Both are expected to miss on first attempt
for a token that is seconds old: the RPC node may not have the transaction yet,
and the DAS indexer lags behind confirmation. Neither is an error.
"""

from __future__ import annotations

import asyncio
from types import TracebackType
from typing import Any, Self

import httpx

from app.core.backoff import BackoffPolicy
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class HeliusError(RuntimeError):
    """A Helius call failed after exhausting retries."""


class HeliusRateLimitError(HeliusError):
    """Helius returned 429."""


class HeliusClient:
    """Async Helius RPC client. Safe to share across tasks."""

    def __init__(
        self,
        *,
        rpc_url: str | None = None,
        client: httpx.AsyncClient | None = None,
        backoff: BackoffPolicy | None = None,
    ) -> None:
        self._rpc_url = rpc_url or settings.HELIUS_RPC_URL
        self._client = client
        self._owns_client = client is None
        self._backoff = backoff or BackoffPolicy.from_settings()

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def start(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(settings.HELIUS_HTTP_TIMEOUT_SECONDS),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
            self._owns_client = True

    async def close(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    @property
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            raise HeliusError(
                "HeliusClient is not started. Call start() or use it as a context manager."
            )
        return self._client

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
                    last_error = HeliusRateLimitError(f"{method} rate limited")
                elif response.status_code >= 500:
                    last_error = HeliusError(f"{method} returned {response.status_code}")
                else:
                    response.raise_for_status()
                    body = response.json()
                    if isinstance(body, dict) and body.get("error"):
                        raise HeliusError(f"{method} error: {body['error']}")
                    return body.get("result") if isinstance(body, dict) else None

            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = exc
            except ValueError as exc:  # malformed JSON body
                last_error = HeliusError(f"{method} returned invalid JSON: {exc}")

            if attempt < attempts:
                delay = self._backoff.delay_for(attempt)
                logger.warning(
                    "helius_call_retry",
                    method=method,
                    attempt=attempt,
                    delay_seconds=round(delay, 2),
                    error=str(last_error),
                )
                await asyncio.sleep(delay)

        raise HeliusError(f"{method} failed after {attempts} attempts: {last_error}")

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
            except HeliusError as exc:
                logger.warning(
                    "helius_get_transaction_failed", signature=signature, error=str(exc)
                )
                result = None

            if isinstance(result, dict):
                return result

            if attempt < total:
                await asyncio.sleep(self._backoff.delay_for(attempt))

        logger.warning("helius_transaction_unavailable", signature=signature, attempts=total)
        return None

    async def get_asset(
        self, mint_address: str, *, attempts: int | None = None
    ) -> dict[str, Any] | None:
        """Fetch DAS metadata for a mint, polling while the indexer catches up."""
        total = attempts or settings.SCANNER_METADATA_ATTEMPTS

        for attempt in range(1, total + 1):
            try:
                result = await self.call("getAsset", {"id": mint_address}, attempts=2)
            except HeliusError as exc:
                logger.debug("helius_get_asset_failed", mint=mint_address, error=str(exc))
                result = None

            # A freshly indexed asset can come back without content; that is a
            # partial response, not a final answer, so keep polling.
            if isinstance(result, dict) and result.get("content"):
                return result

            if attempt < total:
                await asyncio.sleep(self._backoff.delay_for(attempt))

        logger.info("helius_metadata_unresolved", mint=mint_address, attempts=total)
        return None
