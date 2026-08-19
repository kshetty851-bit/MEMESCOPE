"""Filtered, non-authoritative Yellowstone Pump.fun shadow stream."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from app.core.backoff import BackoffPolicy
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.repositories.discovery import DiscoveryObservationRepository
from app.services.discovery.events import DiscoveryEvent
from app.services.discovery.ledger import record_yellowstone_observation
from app.services.scanner.parser import parse_create_event

logger = get_logger(__name__)


class YellowstoneError(RuntimeError):
    """A stream/configuration failure isolated to the shadow process."""


@dataclass(frozen=True, slots=True)
class YellowstoneTransaction:
    signature: str
    slot: int
    logs: tuple[str, ...]
    provider_timestamp: datetime | None
    sequence: int | None = None


class YellowstoneTransport(Protocol):
    async def first_available_slot(self) -> int | None: ...

    async def stream(
        self, *, from_slot: int | None
    ) -> AsyncIterator[YellowstoneTransaction]: ...

    async def close(self) -> None: ...


class GrpcYellowstoneTransport:
    """Real typed gRPC transport using vendored Yellowstone generated stubs."""

    def __init__(self) -> None:
        self._channel: Any = None

    async def _stub(self) -> Any:
        if not settings.YELLOWSTONE_GRPC_URL:
            raise YellowstoneError("YELLOWSTONE_GRPC_URL is not configured")
        try:
            import grpc

            from app.services.discovery.generated import geyser_pb2, geyser_pb2_grpc
        except ImportError as exc:  # pragma: no cover - dependency/build guard
            raise YellowstoneError("Yellowstone gRPC dependencies are unavailable") from exc
        if self._channel is None:
            target = settings.YELLOWSTONE_GRPC_URL.removeprefix("https://").removeprefix(
                "http://"
            )
            self._channel = grpc.aio.secure_channel(
                target,
                grpc.ssl_channel_credentials(),
                options=[
                    ("grpc.max_receive_message_length", settings.YELLOWSTONE_MAX_RECEIVE_BYTES)
                ],
            )
        return geyser_pb2, geyser_pb2_grpc.GeyserStub(self._channel)

    async def first_available_slot(self) -> int | None:
        proto, stub = await self._stub()
        response = await stub.SubscribeReplayInfo(
            proto.SubscribeReplayInfoRequest(), metadata=self._metadata()
        )
        return int(response.first_available) if response.HasField("first_available") else None

    async def stream(self, *, from_slot: int | None) -> AsyncIterator[YellowstoneTransaction]:
        proto, stub = await self._stub()
        request = filtered_pumpfun_subscription(proto, from_slot=from_slot)

        async def requests() -> AsyncIterator[Any]:
            yield request
            while True:
                await asyncio.sleep(15)
                yield proto.SubscribeRequest(ping=proto.SubscribeRequestPing(id=1))

        call = stub.Subscribe(requests(), metadata=self._metadata())
        async for update in call:
            if update.WhichOneof("update_oneof") != "transaction":
                continue
            transaction = update.transaction
            info = transaction.transaction
            logs = tuple(info.meta.log_messages) if not info.meta.log_messages_none else ()
            if not logs:
                continue
            timestamp = None
            if update.HasField("created_at"):
                timestamp = datetime.fromtimestamp(
                    update.created_at.seconds + update.created_at.nanos / 1_000_000_000, tz=UTC
                )
            yield YellowstoneTransaction(
                signature=_b58(info.signature),
                slot=int(transaction.slot),
                logs=logs,
                provider_timestamp=timestamp,
                sequence=int(info.index),
            )

    def _metadata(self) -> tuple[tuple[str, str], ...]:
        token = settings.YELLOWSTONE_X_TOKEN.get_secret_value()
        return (("x-token", token),) if token else ()

    async def close(self) -> None:
        if self._channel is not None:
            await self._channel.close()
            self._channel = None


@dataclass
class YellowstoneStats:
    connected: bool = False
    last_message_at: datetime | None = None
    last_slot: int | None = None
    messages_received: int = 0
    matching_pumpfun_events: int = 0
    unique_mints: int = 0
    duplicates: int = 0
    replays: int = 0
    reconnects: int = 0
    errors: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "connected": self.connected,
            "last_message_at": (
                self.last_message_at.isoformat() if self.last_message_at else None
            ),
            "last_slot": self.last_slot,
            "messages_received": self.messages_received,
            "matching_pumpfun_events": self.matching_pumpfun_events,
            "unique_mints": self.unique_mints,
            "duplicates": self.duplicates,
            "replays": self.replays,
            "reconnects": self.reconnects,
            "errors": self.errors,
        }


class YellowstoneShadowProvider:
    """Observe only.  This class never writes ``discovered_tokens`` or Redis."""

    def __init__(self, *, transport: YellowstoneTransport | None = None) -> None:
        self._transport = transport or GrpcYellowstoneTransport()
        self._backoff = BackoffPolicy.from_settings()
        self._stop = asyncio.Event()
        self.stats = YellowstoneStats()

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        if not settings.YELLOWSTONE_ENABLED:
            logger.info("yellowstone_shadow_disabled")
            return
        if not settings.YELLOWSTONE_SHADOW_MODE:
            logger.error("yellowstone_shadow_refused", reason="shadow_mode_required")
            return
        if (
            not settings.YELLOWSTONE_GRPC_URL
            or not settings.YELLOWSTONE_X_TOKEN.get_secret_value()
        ):
            logger.error("yellowstone_shadow_misconfigured", reason="missing_url_or_token")
            return
        attempt = 0
        try:
            while not self._stop.is_set():
                try:
                    checkpoint = await self._checkpoint()
                    self._restore_stats(checkpoint)
                    from_slot = self._replay_slot(checkpoint)
                    durable_slot = checkpoint.last_durable_slot if checkpoint else None
                    first_available = await self._transport.first_available_slot()
                    if (
                        first_available is not None
                        and from_slot is not None
                        and from_slot < first_available
                    ):
                        raise YellowstoneError(
                            "replay gap: checkpoint "
                            f"{from_slot} predates provider {first_available}"
                        )
                    attempt = 0
                    self.stats.connected = True
                    await self._persist_stats()
                    logger.info("yellowstone_shadow_connected", from_slot=from_slot)
                    async for raw in self._transport.stream(from_slot=from_slot):
                        if self._stop.is_set():
                            break
                        await self._handle(
                            raw,
                            replayed=durable_slot is not None and raw.slot <= durable_slot,
                        )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.stats.connected = False
                    self.stats.errors += 1
                    attempt += 1
                    self.stats.reconnects += 1
                    await self._mark_error(attempt, exc)
                    delay = self._backoff.delay_for(attempt)
                    logger.warning(
                        "yellowstone_shadow_reconnect",
                        error=str(exc),
                        attempt=attempt,
                        delay_seconds=round(delay, 2),
                    )
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(self._stop.wait(), timeout=delay)
        finally:
            self.stats.connected = False
            with contextlib.suppress(Exception):
                await self._persist_stats()
            await self._transport.close()
            logger.info("yellowstone_shadow_stopped", **self.stats.as_dict())

    async def _handle(self, raw: YellowstoneTransaction, *, replayed: bool) -> None:
        self.stats.messages_received += 1
        now = datetime.now(UTC)
        self.stats.last_message_at = now
        self.stats.last_slot = raw.slot
        decoded = parse_create_event(raw.logs)
        if decoded is None:
            await self._persist_stats()
            return
        self.stats.matching_pumpfun_events += 1
        event = DiscoveryEvent(
            mint_address=decoded.mint_address,
            observed_at=now,
            slot=raw.slot,
            signature=raw.signature,
            source="yellowstone_grpc",
            program=settings.PUMPFUN_PROGRAM_ID,
            event_type="pumpfun_create_event",
            provider_timestamp=raw.provider_timestamp or decoded.block_time,
            ingest_timestamp=datetime.now(UTC),
            replayed=replayed,
            reconnect_generation=self.stats.reconnects,
            provider_sequence=raw.sequence,
        )
        inserted = await record_yellowstone_observation(event)
        if inserted:
            self.stats.unique_mints += 1
            if replayed:
                self.stats.replays += 1
        else:
            self.stats.duplicates += 1
        await self._persist_stats()

    async def _checkpoint(self) -> Any:
        async with SessionFactory() as session:
            return await DiscoveryObservationRepository(session).checkpoint("pumpfun")

    def _replay_slot(self, checkpoint: Any) -> int | None:
        if checkpoint is None or checkpoint.last_durable_slot is None:
            return None
        return max(
            0,
            int(checkpoint.last_durable_slot) - settings.YELLOWSTONE_REPLAY_OVERLAP_SLOTS,
        )

    def _restore_stats(self, checkpoint: Any) -> None:
        """Do not reset durable observability counters after a process restart."""
        if checkpoint is None:
            return
        for field in (
            "messages_received",
            "matching_pumpfun_events",
            "unique_mints",
            "duplicates",
            "replays",
            "errors",
        ):
            current = getattr(self.stats, field)
            durable = getattr(checkpoint, field)
            setattr(self.stats, field, max(current, durable))

    async def _mark_error(self, generation: int, exc: Exception) -> None:
        async with SessionFactory() as session:
            repository = DiscoveryObservationRepository(session)
            await repository.mark_stream_error(
                stream_name="pumpfun",
                reconnect_generation=generation,
                error=f"{type(exc).__name__}: {exc}",
            )
            await repository.update_stream_state(
                stream_name="pumpfun",
                last_message_at=self.stats.last_message_at,
                last_slot=self.stats.last_slot,
                reconnect_generation=self.stats.reconnects,
                connected=False,
                messages_received=self.stats.messages_received,
                matching_pumpfun_events=self.stats.matching_pumpfun_events,
                unique_mints=self.stats.unique_mints,
                duplicates=self.stats.duplicates,
                replays=self.stats.replays,
                errors=self.stats.errors,
            )
            await session.commit()

    async def _persist_stats(self) -> None:
        async with SessionFactory() as session:
            await DiscoveryObservationRepository(session).update_stream_state(
                stream_name="pumpfun",
                last_message_at=self.stats.last_message_at,
                last_slot=self.stats.last_slot,
                reconnect_generation=self.stats.reconnects,
                connected=self.stats.connected,
                messages_received=self.stats.messages_received,
                matching_pumpfun_events=self.stats.matching_pumpfun_events,
                unique_mints=self.stats.unique_mints,
                duplicates=self.stats.duplicates,
                replays=self.stats.replays,
                errors=self.stats.errors,
            )
            await session.commit()


def _b58(value: bytes) -> str:
    from app.services.curve.pda import b58encode

    return b58encode(value)


def filtered_pumpfun_subscription(proto: Any, *, from_slot: int | None) -> Any:
    """Build the sole Phase-1 transaction filter: confirmed Pump.fun only."""
    request = proto.SubscribeRequest()
    request.commitment = proto.CONFIRMED
    request.transactions["pumpfun"].vote = False
    request.transactions["pumpfun"].failed = False
    request.transactions["pumpfun"].account_include.extend(settings.YELLOWSTONE_PROGRAM_IDS)
    if from_slot is not None:
        request.from_slot = from_slot
    return request
