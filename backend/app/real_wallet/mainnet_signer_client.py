"""API-side Unix socket client for the isolated mainnet signer.

Asks one question and receives a public key. No secret path, no transaction
bytes and no signature ever cross this boundary — there is nothing to sign.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.core.config import settings


class MainnetSignerUnavailableError(RuntimeError):
    """The API cannot contact the separately deployed mainnet signer."""


class MainnetSignerRejectedError(RuntimeError):
    """The isolated signer refused to identify itself."""


class UnixMainnetSignerClient:
    async def identity(self) -> dict[str, Any]:
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
            writer.write((json.dumps({"op": "identity"}) + "\n").encode("utf-8"))
            await writer.drain()
            raw = await asyncio.wait_for(reader.readline(), timeout=10)
        except (OSError, asyncio.TimeoutError) as exc:
            raise MainnetSignerUnavailableError("mainnet_signer_timeout") from exc
        finally:
            writer.close()
            await writer.wait_closed()
        body = json.loads(raw.decode("utf-8"))
        if not body.get("ok"):
            raise MainnetSignerRejectedError(body.get("error", "mainnet_signer_refused"))
        return body
