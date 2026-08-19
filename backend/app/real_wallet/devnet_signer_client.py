"""API-side Unix socket client for the isolated Phase 2 signer."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from app.core.config import settings


class DevnetSignerUnavailableError(RuntimeError):
    """The API cannot contact the separately deployed signer service."""


class DevnetSignerRejectedError(RuntimeError):
    """The isolated signer rejected its independently reloaded intent."""


class UnixDevnetSignerClient:
    """Send an ID only; transaction bytes and secret-file paths never cross here."""

    async def sign(self, intent_id: uuid.UUID) -> str:
        socket_path = settings.PHASE2_DEVNET_SIGNER_SOCKET.strip()
        if not socket_path:
            raise DevnetSignerUnavailableError("devnet_signer_socket_not_configured")
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(socket_path), timeout=3
            )
            writer.write(
                (
                    json.dumps({"intent_id": str(intent_id)}, separators=(",", ":")) + "\n"
                ).encode("utf-8")
            )
            await writer.drain()
            raw = await asyncio.wait_for(reader.readline(), timeout=20)
            writer.close()
            await writer.wait_closed()
            payload: Any = json.loads(raw.decode("utf-8"))
        except (OSError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            raise DevnetSignerUnavailableError("devnet_signer_unavailable") from exc
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise DevnetSignerRejectedError("devnet_signer_rejected_intent")
        signature = payload.get("signature")
        if not isinstance(signature, str):
            raise DevnetSignerRejectedError("devnet_signer_invalid_response")
        return signature
