"""API-side Unix socket client for the isolated mainnet signer.

Two questions cross this boundary, and only two: "who are you?" and "sign intent
<id>". Nothing else — no secret path, no transaction bytes, no assembled message.

That asymmetry is the architecture. The signer RELOADS the intent from Postgres,
re-verifies the chain, re-checks every top-level program against the allowlist
and recomputes the fingerprint before it will produce a signature, so this
process asking for one does not get to choose what is in it. A compromised
caller can ask; it cannot dictate.

The signature comes back and is handed straight to the transport. It is
bearer-grade material — whoever holds it can broadcast it — so it lives in a
local for the length of one call and is never persisted or logged.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from app.core.config import settings


class MainnetSignerUnavailableError(RuntimeError):
    """The API cannot contact the separately deployed mainnet signer."""


class MainnetSignerRejectedError(RuntimeError):
    """The isolated signer refused the request."""


class UnixMainnetSignerClient:
    async def identity(self) -> dict[str, Any]:
        """The public key it holds, and whether it matches the pinned one."""
        return await self._ask({"op": "identity"})

    async def sign(self, intent_id: uuid.UUID) -> dict[str, Any]:
        """Ask for one signature over one intent, named only by its id.

        Everything deciding WHAT gets signed is reloaded on the far side. This
        sends an id and receives `signed_transaction`, `signature` and
        `message_fingerprint`; only the last two may be recorded.
        """
        return await self._ask({"op": "sign", "intent_id": str(intent_id)})

    async def sign_withdrawal(self, encoded_transaction: str) -> dict[str, Any]:
        """Ask for a signature over a native SOL transfer.

        Unlike `sign`, this sends BYTES — and that is safe for one reason: the
        signer re-derives the destination from those bytes and compares it
        against the withdrawal address in its own environment. Handing it a
        transaction that pays anyone else gets a refusal, not a signature.
        """
        return await self._ask(
            {"op": "sign_withdrawal", "transaction": encoded_transaction}
        )

    async def _ask(self, request: dict[str, Any]) -> dict[str, Any]:
        socket_path = settings.MAINNET_SIGNER_SOCKET.strip()
        if not socket_path:
            raise MainnetSignerUnavailableError("mainnet_signer_socket_not_configured")
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(socket_path), timeout=3
            )
        except (OSError, asyncio.TimeoutError) as exc:
            raise MainnetSignerUnavailableError("mainnet_signer_unreachable") from exc
        try:
            writer.write((json.dumps(request) + "\n").encode("utf-8"))
            await writer.drain()
            raw = await asyncio.wait_for(reader.readline(), timeout=20)
        except (OSError, asyncio.TimeoutError) as exc:
            raise MainnetSignerUnavailableError("mainnet_signer_timeout") from exc
        finally:
            writer.close()
            await writer.wait_closed()
        body = json.loads(raw.decode("utf-8"))
        if not body.get("ok"):
            raise MainnetSignerRejectedError(body.get("error", "mainnet_signer_refused"))
        return body
