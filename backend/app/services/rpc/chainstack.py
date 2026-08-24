"""Chainstack Solana Mainnet — standard JSON-RPC behind a dedicated endpoint.

Nothing vendor-specific: Chainstack speaks the plain Solana API, so the whole
implementation is the standard client pointed at the configured endpoint. The
URL carries the access token, so it is injected from settings, never logged
(`describe()` redacts), and never defaulted to a public host — an unset
endpoint fails loudly at construction rather than silently degrading to a node
nobody chose.
"""

from __future__ import annotations

from typing import ClassVar

from app.core.config import settings
from app.services.rpc.base import RpcError
from app.services.rpc.standard import NO_DAS_REASON, StandardSolanaRPC


class ChainstackRPC(StandardSolanaRPC):
    name: ClassVar[str] = "chainstack"
    supports_metadata: ClassVar[bool] = False
    metadata_unavailable_reason: ClassVar[str | None] = NO_DAS_REASON

    def __init__(self, **kwargs: object) -> None:
        url = settings.CHAINSTACK_RPC_URL
        if not url:
            raise RpcError(
                "CHAINSTACK_RPC_URL is not configured. Chainstack is opt-in: "
                "set the endpoint (it embeds the access token) before selecting "
                "this provider."
            )
        super().__init__(rpc_url=url, **kwargs)  # type: ignore[arg-type]
