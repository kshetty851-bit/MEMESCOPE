"""Solana token discovery scanner.

Shape of the pipeline:

    logsSubscribe ──▶ cheap log filter ──▶ bounded queue ──▶ N workers
                                                                      │
                                          getTransaction + getAsset ◀──┤
                                                                      │
                                    idempotent insert ──▶ Redis publish

The reader and the workers are separated by a bounded queue on purpose. The
stream delivers hundreds of transactions per second while resolving one token
costs two RPC round trips; without that separation a burst of launches would
either block the socket (and get us disconnected) or grow memory without limit.
When the queue is full we drop the newest event and say so in the logs, because
a scanner that dies under load is worse than one that misses a token.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import websockets
from websockets.asyncio.client import ClientConnection

from app.core.backoff import BackoffPolicy
from app.core.config import settings
from app.core.events import publish_token_discovered
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.db.session import SessionFactory
from app.health.service import publish_scanner_state
from app.models.token import MetadataStatus
from app.repositories.token import TokenRepository
from app.services.rpc.base import SolanaRPC
from app.services.rpc.registry import get_rpc
from app.services.scanner.parser import (
    LogEvent,
    TokenCreation,
    TokenMetadata,
    is_token_creation_log,
    parse_asset_metadata,
    parse_create_event,
    parse_log_notification,
    parse_transaction,
)

logger = get_logger(__name__)

DEDUPE_PREFIX = "scanner:seen:"


@dataclass
class ScannerStats:
    events_received: int = 0
    events_filtered: int = 0
    events_queued: int = 0
    events_dropped: int = 0
    tokens_discovered: int = 0
    tokens_duplicate: int = 0
    resolve_failures: int = 0
    #: How each creation was resolved. The split is the whole point of reading
    #: the log event: a token resolved from logs cost no RPC call at all, and
    #: on a rate-limited public endpoint that is the difference between
    #: capturing it and losing it.
    resolved_from_logs: int = 0
    resolved_from_transaction: int = 0
    reconnects: int = 0
    #: Failures since the last clean connection. `reconnects` is the lifetime
    #: total and never falls, so it cannot answer "is it failing *now*" — which
    #: is the only question escalation and health care about.
    consecutive_failures: int = 0
    last_failure_reason: str | None = None
    started_at: datetime | None = field(default=None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "events_received": self.events_received,
            "events_filtered": self.events_filtered,
            "events_queued": self.events_queued,
            "events_dropped": self.events_dropped,
            "tokens_discovered": self.tokens_discovered,
            "resolved_from_logs": self.resolved_from_logs,
            "resolved_from_transaction": self.resolved_from_transaction,
            "tokens_duplicate": self.tokens_duplicate,
            "resolve_failures": self.resolve_failures,
            "reconnects": self.reconnects,
            "consecutive_failures": self.consecutive_failures,
            "last_failure_reason": self.last_failure_reason,
            "started_at": self.started_at.isoformat() if self.started_at else None,
        }


class TokenScanner:
    def __init__(
        self,
        *,
        rpc: SolanaRPC | None = None,
        ws_url: str | None = None,
        programs: list[str] | None = None,
    ) -> None:
        self._rpc = rpc or get_rpc()
        self._ws_url = ws_url or settings.rpc_ws_url
        self._programs = programs or list(settings.SCANNER_WATCH_PROGRAMS)
        self._queue: asyncio.Queue[LogEvent] = asyncio.Queue(
            maxsize=settings.SCANNER_QUEUE_SIZE
        )
        self._backoff = BackoffPolicy.from_settings()
        self._stop = asyncio.Event()
        self._workers: list[asyncio.Task[None]] = []
        self.stats = ScannerStats()

    # --- Lifecycle ----------------------------------------------------------

    async def run(self) -> None:
        """Run until `stop()` is called. Reconnects on its own."""
        # Only the vendor implementation needs a key. Against a standard
        # endpoint there is nothing to configure, which is the point of the
        # abstraction — the scanner subscribes with `logsSubscribe`, which every
        # compliant node serves.
        if settings.uses_helius and not settings.helius_configured:
            raise RuntimeError("HELIUS_API_KEY is not configured; scanner cannot start.")

        self.stats.started_at = datetime.now(UTC)
        await self._rpc.start()

        logger.info(
            "scanner_started",
            programs=self._programs,
            commitment=settings.SCANNER_COMMITMENT,
            workers=settings.SCANNER_WORKER_CONCURRENCY,
            queue_size=settings.SCANNER_QUEUE_SIZE,
        )

        self._workers = [
            asyncio.create_task(self._worker(index), name=f"scanner-worker-{index}")
            for index in range(settings.SCANNER_WORKER_CONCURRENCY)
        ]

        try:
            await self._stream_forever()
        finally:
            for worker in self._workers:
                worker.cancel()
            await asyncio.gather(*self._workers, return_exceptions=True)
            await self._rpc.close()
            logger.info("scanner_stopped", **self.stats.as_dict())

    def stop(self) -> None:
        self._stop.set()

    # --- Stream -------------------------------------------------------------

    async def _stream_forever(self) -> None:
        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    self._ws_url,
                    ping_interval=settings.SCANNER_WS_PING_INTERVAL_SECONDS,
                    ping_timeout=settings.SCANNER_WS_PING_INTERVAL_SECONDS,
                    max_size=16 * 1024 * 1024,
                    close_timeout=5,
                ) as ws:
                    await self._subscribe(ws)
                    # A clean connection resets the ladder and clears the
                    # published failure, so recovery is visible immediately
                    # rather than at the next health poll.
                    self.stats.consecutive_failures = 0
                    self.stats.last_failure_reason = None
                    await self._publish_state(connected=True)
                    await self._consume(ws)

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._stop.is_set():
                    break
                self.stats.reconnects += 1
                self.stats.consecutive_failures += 1
                self.stats.last_failure_reason = f"{type(exc).__name__}: {exc}"
                delay = self._backoff.delay_for(self.stats.consecutive_failures)
                self._log_reconnect(exc, delay)
                await self._publish_state(connected=False)
                await asyncio.sleep(delay)

    def _log_reconnect(self, exc: Exception, delay: float) -> None:
        """Escalate a persistent outage instead of warning about it forever.

        A single failed reconnect is routine and belongs at `warning`. Nine
        hundred of them is an outage, and logging the nine-hundredth the same
        way as the first is how four days of dead discovery went unnoticed —
        every line looked exactly like the transient case it was not.

        Past the threshold the level becomes ERROR, but only every Nth attempt:
        an unattended weekend outage should page once and leave a readable log,
        not a million identical lines.
        """
        attempt = self.stats.consecutive_failures
        fields: dict[str, Any] = {
            "error": str(exc),
            "error_type": type(exc).__name__,
            "attempt": attempt,
            "delay_seconds": round(delay, 2),
        }

        if attempt < settings.SCANNER_RECONNECT_ERROR_ATTEMPTS:
            logger.warning("scanner_reconnect", **fields)
            return

        first_escalation = attempt == settings.SCANNER_RECONNECT_ERROR_ATTEMPTS
        due = (attempt - settings.SCANNER_RECONNECT_ERROR_ATTEMPTS) % (
            settings.SCANNER_RECONNECT_ERROR_EVERY
        ) == 0
        if first_escalation or due:
            logger.error(
                "scanner_reconnect_failing",
                **fields,
                threshold=settings.SCANNER_RECONNECT_ERROR_ATTEMPTS,
                detail=(
                    "Discovery has stopped. The scanner cannot reach Helius and "
                    "is no longer finding tokens; this is not a transient blip."
                ),
            )

    async def _publish_state(self, *, connected: bool) -> None:
        """Make the connection state readable from the API container."""
        await publish_scanner_state(
            connected=connected,
            reconnect_attempts=self.stats.consecutive_failures,
            failure_reason=self.stats.last_failure_reason,
        )

    async def _subscribe(self, ws: ClientConnection) -> None:
        for index, program in enumerate(self._programs):
            await ws.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": index + 1,
                        "method": "logsSubscribe",
                        "params": [
                            {"mentions": [program]},
                            {"commitment": settings.SCANNER_COMMITMENT},
                        ],
                    }
                )
            )
        logger.info("scanner_subscribed", programs=self._programs)

    async def _consume(self, ws: ClientConnection) -> None:
        while not self._stop.is_set():
            raw = await ws.recv()
            self.stats.events_received += 1

            try:
                message = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(message, dict) or message.get("method") != "logsNotification":
                continue

            event = parse_log_notification(message)
            if event is None or not is_token_creation_log(event.logs):
                continue

            self.stats.events_filtered += 1
            try:
                self._queue.put_nowait(event)
                self.stats.events_queued += 1
            except asyncio.QueueFull:
                self.stats.events_dropped += 1
                logger.warning(
                    "scanner_queue_full",
                    signature=event.signature,
                    dropped_total=self.stats.events_dropped,
                )

    # --- Workers ------------------------------------------------------------

    async def _worker(self, index: int) -> None:
        while True:
            event = await self._queue.get()
            try:
                await self._handle_event(event)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.stats.resolve_failures += 1
                logger.exception(
                    "scanner_event_failed", signature=event.signature, worker=index
                )
            finally:
                self._queue.task_done()

    def _from_logs(
        self, event: LogEvent
    ) -> tuple[TokenCreation, TokenMetadata | None] | None:
        """Resolve a creation from the log payload alone, or None.

        The fast path, and the one that survives a rate limit: the launchpad's
        own creation event carries the mint, the creator and the token's
        metadata, so nothing here touches the network. `decimals` is absent from
        the event and stays null rather than being assumed.
        """
        decoded = parse_create_event(event.logs)
        if decoded is None:
            return None

        creation = TokenCreation(
            mint_address=decoded.mint_address,
            signature=event.signature,
            slot=event.slot,
            creator_address=decoded.creator_address,
            decimals=None,
            block_time=decoded.block_time,
            source_program=self._programs[0] if self._programs else None,
        )
        metadata = TokenMetadata(
            name=decoded.name,
            symbol=decoded.symbol,
            metadata_uri=decoded.metadata_uri,
            decimals=None,
        )
        return creation, metadata

    async def _from_transaction(
        self, event: LogEvent
    ) -> tuple[TokenCreation, TokenMetadata | None] | None:
        """Resolve a creation by fetching the transaction. The fallback path.

        Unchanged behaviour, and deliberately still here: it is what keeps the
        scanner launchpad-agnostic. A program that emits `InitializeMint`
        without a decodable creation event is discovered exactly as before.
        """
        transaction = await self._rpc.get_transaction(event.signature)
        if transaction is None:
            self.stats.resolve_failures += 1
            return None

        creation = parse_transaction(
            transaction,
            signature=event.signature,
            fallback_slot=event.slot,
            source_program=self._programs[0] if self._programs else None,
        )
        if creation is None:
            return None

        # `None` covers two different facts and both end the same way: the
        # indexer has not caught up yet, or this node does not index at all
        # (`supports_metadata` is False on a plain validator). Either leaves the
        # token at `MetadataStatus.PENDING` — unresolved so far, not nameless —
        # and a later resolution needs no backfill.
        metadata = None
        asset = await self._rpc.get_asset(creation.mint_address)
        if asset is not None:
            metadata = parse_asset_metadata(asset)
        return creation, metadata

    async def _handle_event(self, event: LogEvent) -> None:
        resolved: tuple[TokenCreation, TokenMetadata | None] | None = self._from_logs(
            event
        )
        if resolved is not None:
            self.stats.resolved_from_logs += 1
        else:
            resolved = await self._from_transaction(event)
            if resolved is None:
                return
            self.stats.resolved_from_transaction += 1

        creation, metadata = resolved

        # Cheap pre-check against Redis so a repeated event does not cost a
        # database round trip. The unique index remains the real guarantee.
        if await self._seen_recently(creation.mint_address):
            self.stats.tokens_duplicate += 1
            logger.debug("scanner_duplicate_suppressed", mint=creation.mint_address)
            return

        logger.info(
            "token_detected",
            mint=creation.mint_address,
            signature=creation.signature,
            slot=creation.slot,
            creator=creation.creator_address,
        )

        values: dict[str, Any] = {
            "mint_address": creation.mint_address,
            "signature": creation.signature,
            "slot": creation.slot,
            "creator_address": creation.creator_address,
            "decimals": creation.decimals,
            "block_time": creation.block_time,
            "source_program": creation.source_program,
            "metadata_status": MetadataStatus.PENDING,
        }
        if metadata is not None:
            values.update(
                name=metadata.name,
                symbol=metadata.symbol,
                metadata_uri=metadata.metadata_uri,
                decimals=creation.decimals
                if creation.decimals is not None
                else metadata.decimals,
                metadata_status=(
                    MetadataStatus.RESOLVED
                    if (metadata.name or metadata.symbol)
                    else MetadataStatus.PENDING
                ),
                metadata_attempts=1,
            )
        else:
            values["metadata_attempts"] = 1

        async with SessionFactory() as session:
            repository = TokenRepository(session)
            inserted = await repository.insert_if_absent(values)
            if inserted is None:
                await session.rollback()
                self.stats.tokens_duplicate += 1
                logger.debug("token_duplicate_ignored", mint=creation.mint_address)
                return

            payload = _to_payload(inserted)
            await session.commit()

        self.stats.tokens_discovered += 1
        logger.info(
            "token_saved",
            mint=payload["mint_address"],
            name=payload["name"],
            symbol=payload["symbol"],
            metadata_status=payload["metadata_status"],
        )

        receivers = await publish_token_discovered(payload)
        logger.info(
            "token_broadcast", mint=payload["mint_address"], redis_subscribers=receivers
        )

    async def _seen_recently(self, mint_address: str) -> bool:
        """Mark a mint as seen; True if it already was.

        `SET NX` is atomic, so two workers handling duplicate events for the
        same mint cannot both proceed.
        """
        try:
            was_set = await get_redis().set(
                f"{DEDUPE_PREFIX}{mint_address}",
                "1",
                ex=settings.SCANNER_DEDUPE_TTL_SECONDS,
                nx=True,
            )
            return not bool(was_set)
        except Exception:
            logger.warning("scanner_dedupe_unavailable", exc_info=True)
            return False


def _to_payload(token: Any) -> dict[str, Any]:
    return {
        "id": str(token.id),
        "mint_address": token.mint_address,
        "name": token.name,
        "symbol": token.symbol,
        "decimals": token.decimals,
        "metadata_uri": token.metadata_uri,
        "creator_address": token.creator_address,
        "signature": token.signature,
        "slot": token.slot,
        "block_time": token.block_time.isoformat() if token.block_time else None,
        "discovered_at": token.discovered_at.isoformat() if token.discovered_at else None,
        "source_program": token.source_program,
        "metadata_status": str(token.metadata_status),
    }


async def run_scanner() -> None:
    """Entrypoint used by the scanner process."""
    from app.core.redis import close_redis, init_redis

    scanner = TokenScanner()
    await init_redis()

    loop = asyncio.get_running_loop()
    import signal

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, scanner.stop)

    try:
        await scanner.run()
    finally:
        await close_redis()
