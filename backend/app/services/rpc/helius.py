"""Helius: standard JSON-RPC, plus the DAS metadata read.

One implementation among several now, rather than the assumption the platform
was built on. Everything it inherits is standard; the only thing it adds is
`getAsset`, which is what a DAS indexer can answer and a plain validator cannot.

That single method is the entire vendor surface. Naming it here — instead of
letting it sit unmarked in a shared client — is what makes the dependency
visible and, as of this sprint, optional.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import httpx

from app.core.backoff import BackoffPolicy
from app.core.config import settings
from app.core.logging import get_logger
from app.services.rpc.base import RpcError
from app.services.rpc.standard import StandardSolanaRPC

logger = get_logger(__name__)


class HeliusRPC(StandardSolanaRPC):
    """Helius. Standard everywhere except the metadata read."""

    name: ClassVar[str] = "helius"
    supports_metadata: ClassVar[bool] = True
    metadata_unavailable_reason: ClassVar[str | None] = None

    def __init__(
        self,
        *,
        rpc_url: str | None = None,
        client: httpx.AsyncClient | None = None,
        backoff: BackoffPolicy | None = None,
    ) -> None:
        super().__init__(
            rpc_url=rpc_url or settings.HELIUS_RPC_URL,
            client=client,
            backoff=backoff,
        )

    async def get_asset(
        self, mint_address: str, *, attempts: int | None = None
    ) -> dict[str, Any] | None:
        """Fetch DAS metadata for a mint, polling while the indexer catches up.

        The poll is not defensive coding: the indexer lags confirmation, so a
        token seconds old is expected to miss on the first attempt. Returning
        `None` after the last one leaves the token at `MetadataStatus.PENDING`,
        which is the honest state — unresolved so far, not nameless.
        """
        total = attempts or settings.SCANNER_METADATA_ATTEMPTS

        for attempt in range(1, total + 1):
            try:
                result = await self.call("getAsset", {"id": mint_address}, attempts=2)
            except RpcError as exc:
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
