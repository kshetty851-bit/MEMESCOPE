"""Persistence for source-observation telemetry.  Owns no transaction."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.discovery import (
    DiscoveryObservationSource,
    DiscoverySourceObservation,
    YellowstoneStreamCheckpoint,
)
from app.services.discovery.events import DiscoveryEvent


class DiscoveryObservationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, event: DiscoveryEvent, *, provider_name: str) -> bool:
        result = await self._session.execute(
            insert(DiscoverySourceObservation)
            .values(
                source=DiscoveryObservationSource(event.source),
                provider_name=provider_name,
                mint_address=event.mint_address,
                signature=event.signature,
                slot=event.slot,
                program=event.program,
                event_type=event.event_type,
                observed_at=event.observed_at,
                provider_timestamp=event.provider_timestamp,
                ingested_at=event.ingested_at,
                replayed=event.replayed,
                reconnect_generation=event.reconnect_generation,
                provider_sequence=event.provider_sequence,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    DiscoverySourceObservation.source,
                    DiscoverySourceObservation.signature,
                    DiscoverySourceObservation.mint_address,
                ]
            )
            .returning(DiscoverySourceObservation.id)
        )
        return result.scalar_one_or_none() is not None

    async def checkpoint(self, stream_name: str) -> YellowstoneStreamCheckpoint | None:
        return await self._session.get(YellowstoneStreamCheckpoint, stream_name)

    async def advance_checkpoint(
        self,
        *,
        stream_name: str,
        slot: int,
        signature: str,
        observed_at: datetime,
        reconnect_generation: int,
    ) -> None:
        statement = insert(YellowstoneStreamCheckpoint).values(
            stream_name=stream_name,
            last_durable_slot=slot,
            last_durable_signature=signature,
            last_message_at=observed_at,
            reconnect_generation=reconnect_generation,
            connected=True,
            last_error=None,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[YellowstoneStreamCheckpoint.stream_name],
            set_={
                "last_durable_slot": case(
                    (YellowstoneStreamCheckpoint.last_durable_slot.is_(None), slot),
                    (YellowstoneStreamCheckpoint.last_durable_slot <= slot, slot),
                    else_=YellowstoneStreamCheckpoint.last_durable_slot,
                ),
                "last_durable_signature": case(
                    (YellowstoneStreamCheckpoint.last_durable_slot.is_(None), signature),
                    (YellowstoneStreamCheckpoint.last_durable_slot <= slot, signature),
                    else_=YellowstoneStreamCheckpoint.last_durable_signature,
                ),
                "last_message_at": observed_at,
                "reconnect_generation": reconnect_generation,
                "connected": True,
                "last_error": None,
            },
        )
        await self._session.execute(statement)

    async def mark_stream_error(
        self, *, stream_name: str, reconnect_generation: int, error: str
    ) -> None:
        statement = insert(YellowstoneStreamCheckpoint).values(
            stream_name=stream_name,
            reconnect_generation=reconnect_generation,
            connected=False,
            last_error=error[:500],
        )
        statement = statement.on_conflict_do_update(
            index_elements=[YellowstoneStreamCheckpoint.stream_name],
            set_={
                "reconnect_generation": reconnect_generation,
                "connected": False,
                "last_error": error[:500],
            },
        )
        await self._session.execute(statement)

    async def update_stream_state(
        self,
        *,
        stream_name: str,
        last_message_at: datetime | None,
        last_slot: int | None,
        reconnect_generation: int,
        connected: bool,
        messages_received: int,
        matching_pumpfun_events: int,
        unique_mints: int,
        duplicates: int,
        replays: int,
        errors: int,
    ) -> None:
        """Persist cumulative process counters without touching the checkpoint."""
        values = {
            "stream_name": stream_name,
            "last_message_at": last_message_at,
            "reconnect_generation": reconnect_generation,
            "connected": connected,
            "messages_received": messages_received,
            "matching_pumpfun_events": matching_pumpfun_events,
            "unique_mints": unique_mints,
            "duplicates": duplicates,
            "replays": replays,
            "errors": errors,
        }
        if last_slot is not None:
            values["last_received_slot"] = last_slot
        if connected:
            values["last_error"] = None
        statement = insert(YellowstoneStreamCheckpoint).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[YellowstoneStreamCheckpoint.stream_name], set_=values
        )
        await self._session.execute(statement)

    async def summary(self) -> dict[str, object]:
        source = DiscoverySourceObservation.source
        mint = DiscoverySourceObservation.mint_address
        firsts = (
            select(
                mint.label("mint"),
                source.label("source"),
                func.min(DiscoverySourceObservation.observed_at).label("first_at"),
            )
            .group_by(mint, source)
            .subquery()
        )
        paired = (
            select(
                firsts.c.mint,
                func.min(firsts.c.first_at)
                .filter(firsts.c.source == DiscoveryObservationSource.RPC_WS)
                .label("rpc_at"),
                func.min(firsts.c.first_at)
                .filter(firsts.c.source == DiscoveryObservationSource.YELLOWSTONE_GRPC)
                .label("yellowstone_at"),
            )
            .group_by(firsts.c.mint)
            .subquery()
        )
        rows = (
            await self._session.execute(select(paired.c.rpc_at, paired.c.yellowstone_at))
        ).all()
        both = [row for row in rows if _has_both_sources(row)]
        deltas = sorted((row.yellowstone_at - row.rpc_at).total_seconds() for row in both)

        def percentile(value: float) -> float | None:
            if not deltas:
                return None
            return deltas[min(len(deltas) - 1, round((len(deltas) - 1) * value))]

        return {
            "rpc_only": sum(
                row.rpc_at is not None and row.yellowstone_at is None for row in rows
            ),
            "yellowstone_only": sum(
                row.yellowstone_at is not None and row.rpc_at is None for row in rows
            ),
            "both_detected": len(both),
            "yellowstone_first": sum(delta < 0 for delta in deltas),
            "rpc_first": sum(delta > 0 for delta in deltas),
            "latency_delta_seconds": {
                "p50": percentile(0.5),
                "p95": percentile(0.95),
                "p99": percentile(0.99),
            },
        }


def _has_both_sources(row: Any) -> bool:
    """Keep the overlap predicate shared and readable for comparison rows."""
    return row.rpc_at is not None and row.yellowstone_at is not None
