"""Read-only operational visibility for discovery transport research."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import DbSession
from app.core.config import settings
from app.repositories.discovery import DiscoveryObservationRepository

router = APIRouter(prefix="/discovery", tags=["discovery"])


@router.get("/yellowstone-shadow", summary="Yellowstone shadow status and source comparison")
async def yellowstone_shadow(session: DbSession) -> dict[str, object]:
    """Observational only; this endpoint cannot enable or alter a stream."""
    repository = DiscoveryObservationRepository(session)
    checkpoint = await repository.checkpoint("pumpfun")
    return {
        "enabled": settings.YELLOWSTONE_ENABLED,
        "shadow_mode": settings.YELLOWSTONE_SHADOW_MODE,
        "connection": {
            "connected": checkpoint.connected if checkpoint else False,
            "last_message_at": checkpoint.last_message_at if checkpoint else None,
            "last_slot": checkpoint.last_received_slot if checkpoint else None,
            "last_durable_slot": checkpoint.last_durable_slot if checkpoint else None,
            "reconnect_generation": checkpoint.reconnect_generation if checkpoint else 0,
            "last_error": checkpoint.last_error if checkpoint else None,
        },
        "metrics": {
            "messages_received": checkpoint.messages_received if checkpoint else 0,
            "matching_pumpfun_events": checkpoint.matching_pumpfun_events if checkpoint else 0,
            "unique_mints": checkpoint.unique_mints if checkpoint else 0,
            "duplicates": checkpoint.duplicates if checkpoint else 0,
            "replays": checkpoint.replays if checkpoint else 0,
            "reconnects": checkpoint.reconnect_generation if checkpoint else 0,
            "errors": checkpoint.errors if checkpoint else 0,
        },
        "comparison": await repository.summary(),
    }
