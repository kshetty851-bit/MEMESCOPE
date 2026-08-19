"""Failure-isolated recording of canonical and shadow observations."""

from __future__ import annotations

from app.db.session import SessionFactory
from app.repositories.discovery import DiscoveryObservationRepository
from app.services.discovery.events import DiscoveryEvent


async def record_rpc_observation(event: DiscoveryEvent) -> bool:
    """Best-effort RPC telemetry; never participates in canonical ingestion."""
    async with SessionFactory() as session:
        inserted = await DiscoveryObservationRepository(session).append(
            event, provider_name="solana_rpc_ws"
        )
        await session.commit()
        return inserted


async def record_yellowstone_observation(
    event: DiscoveryEvent, *, stream_name: str = "pumpfun"
) -> bool:
    """Durably append before advancing the replay checkpoint in one transaction."""
    async with SessionFactory() as session:
        repository = DiscoveryObservationRepository(session)
        inserted = await repository.append(event, provider_name="yellowstone_grpc")
        if inserted:
            await repository.advance_checkpoint(
                stream_name=stream_name,
                slot=event.slot,
                signature=event.signature,
                observed_at=event.observed_at,
                reconnect_generation=event.reconnect_generation,
            )
        await session.commit()
        return inserted
