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
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
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
from app.services.discovery.events import DiscoveryEvent
from app.services.discovery.ledger import record_rpc_observation
from app.services.rpc.base import SolanaRPC
from app.services.rpc.registry import get_rpc
from app.services.scanner.parser import (
    POOL_CREATE_MARKER,
    LogEvent,
    TokenCreation,
    TokenMetadata,
    creation_events_from_block,
    is_token_creation_log,
    parse_asset_metadata,
    parse_create_event,
    parse_log_notification,
    parse_pumpswap_pool_event,
    parse_transaction,
)
from app.services.scanner.trade_events import decode_trade_events
from app.services.scanner.wallet_flow import WalletFlowTracker

logger = get_logger(__name__)

DEDUPE_PREFIX = "scanner:seen:"


@dataclass(frozen=True, slots=True)
class _Resolution:
    """A resolved creation, and the decoder that produced it.

    `event_type` travels with the result rather than being reconstructed from
    the metadata afterwards: it is the research ledger's provenance field, and
    a guess made from "did metadata come back empty" mislabels a pump.fun
    token whose DAS lookup returned nothing as a PumpSwap pool creation.
    """

    creation: TokenCreation
    metadata: TokenMetadata | None
    event_type: str


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
    #: Pool-creation transactions whose event failed to decode. Counted rather
    #: than sent to the transaction fallback: the mint-init in such a
    #: transaction is the pool's LP mint, and "no reading" beats a confident
    #: wrong one.
    pool_events_refused: int = 0
    reconnects: int = 0
    #: Failures since the last clean connection. `reconnects` is the lifetime
    #: total and never falls, so it cannot answer "is it failing *now*" — which
    #: is the only question escalation and health care about.
    consecutive_failures: int = 0
    last_failure_reason: str | None = None
    #: Gap recovery. Slots abandoned is the honest count of what a long outage
    #: cost even after recovery ran — a silent cap would read as full coverage.
    recovery_runs: int = 0
    recovery_slots_scanned: int = 0
    recovery_slots_abandoned: int = 0
    recovery_events_queued: int = 0
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
            "pool_events_refused": self.pool_events_refused,
            "tokens_duplicate": self.tokens_duplicate,
            "resolve_failures": self.resolve_failures,
            "reconnects": self.reconnects,
            "consecutive_failures": self.consecutive_failures,
            "last_failure_reason": self.last_failure_reason,
            "recovery_runs": self.recovery_runs,
            "recovery_slots_scanned": self.recovery_slots_scanned,
            "recovery_slots_abandoned": self.recovery_slots_abandoned,
            "recovery_events_queued": self.recovery_events_queued,
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
        # RPC subscription ids are allocated by the node.  They are the only
        # authoritative way to associate a notification with the program that
        # requested it when more than one launchpad is watched.
        self._subscription_programs: dict[int, str] = {}
        self._queue: asyncio.Queue[LogEvent] = asyncio.Queue(
            maxsize=settings.SCANNER_QUEUE_SIZE
        )
        self._backoff = BackoffPolicy.from_settings()
        self._stop = asyncio.Event()
        self._workers: list[asyncio.Task[None]] = []
        #: Highest slot seen on the live stream — the in-process gap marker.
        #: None until the first notification; a cold start falls back to the
        #: database's highest recently discovered slot.
        self._last_slot: int | None = None
        # Wallet-flow aggregation over the trades already arriving on this
        # socket. `None` when the feature is off, so the hot path costs one
        # attribute check rather than a decode.
        self._flow: WalletFlowTracker | None = (
            WalletFlowTracker(
                capacity=settings.WALLET_FLOW_EVENT_CAPACITY,
                max_mints=settings.WALLET_FLOW_MAX_MINTS,
                ttl_seconds=settings.WALLET_FLOW_TTL_SECONDS,
            )
            if settings.FEATURE_WALLET_FLOW_ENABLED
            else None
        )
        self._flow_decode_failures = 0
        self._recovery: asyncio.Task[None] | None = None
        #: Gap marker queued by a reconnect that arrived while a walk was
        #: already running. The running walk drains it rather than losing it.
        self._pending_recovery_slot: int | None = None
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
            if self._recovery is not None:
                self._recovery.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._recovery
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
                    # Live consumption resumes first; recovery walks the gap
                    # concurrently so a long backfill never delays a live token.
                    self._maybe_start_recovery()
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

    def _record_trades(self, event: LogEvent) -> None:
        """Fold this transaction's trades into the rolling aggregates.

        Keyed by mint when the chain gave one (pump.fun) and by pool otherwise
        (PumpSwap names only the pool). Resolving pool -> mint is deliberately
        left to the reader at decision time, where the mapping this platform
        already stores is available; guessing it here would put a database
        round trip on the socket loop.
        """
        for trade in decode_trade_events(event.logs):
            key = trade.mint or trade.pool
            if key:
                self._flow.apply(key, trade, signature=event.signature)

    # --- Gap recovery -------------------------------------------------------

    def _maybe_start_recovery(self) -> None:
        """Start one recovery walk if none is running. Never overlaps: two
        walks would double the RPC spend for zero extra coverage.

        The gap marker is snapshotted *here*, synchronously, before `_consume`
        resumes on the new connection. Read inside the task it would race the
        live stream: the first notification advances `_last_slot` to the
        current tip within milliseconds of reconnecting, erasing the memory of
        the outage the walk exists to cover — observed live on 2026-08-20,
        when the startup walk silently found "no gap".
        """
        if settings.SCANNER_RECOVERY_MAX_SLOTS <= 0:
            return

        # A second outage while a walk is still running does not forfeit its
        # gap: the marker is queued, and the running walk picks it up when it
        # finishes. Dropping it (the first implementation) silently lost every
        # launch in the second outage, because live consumption had already
        # advanced `_last_slot` past it by the time the walk ended.
        pending = self._last_slot
        if pending is not None:
            self._pending_recovery_slot = (
                pending
                if self._pending_recovery_slot is None
                else min(self._pending_recovery_slot, pending)
            )

        if self._recovery is not None and not self._recovery.done():
            return
        self._recovery = asyncio.create_task(self._recovery_loop(), name="scanner-recovery")

    async def _recovery_loop(self) -> None:
        """Drain queued gap markers, one walk at a time and never concurrently."""
        while not self._stop.is_set():
            marker = self._pending_recovery_slot
            self._pending_recovery_slot = None
            await self._recover_gap(last_seen_slot=marker)
            if self._pending_recovery_slot is None:
                return

    async def _recover_gap(self, *, last_seen_slot: int | None) -> None:
        """Walk the slots missed while disconnected and requeue their creations.

        Authoritative by construction: `getBlock` returns every transaction's
        log messages, so the walk applies exactly the live pre-filter and the
        live event decoders to exactly the data the subscription would have
        delivered. Timestamps come from the chain (`blockTime`); nothing is
        fabricated — a recovered token's `discovered_at` is the moment we
        actually discovered it, and its ledger observation is marked replayed.

        Storm-safe four ways: one walk at a time, a hard slot cap (abandoned
        slots are counted and logged, never hidden), a delay between block
        fetches, and `await queue.put` — recovery yields to live traffic
        instead of overflowing the bounded queue.
        """
        try:
            current = await self._rpc.call(
                "getSlot", [{"commitment": settings.SCANNER_COMMITMENT}]
            )
            if not isinstance(current, int):
                return

            last = last_seen_slot
            if last is None:
                # Cold start: the durable marker is the highest slot the
                # previous process discovered at.
                async with SessionFactory() as session:
                    last = await TokenRepository(session).max_recent_slot(
                        since=datetime.now(UTC) - timedelta(hours=48)
                    )
            if last is None or current <= last + 1:
                return

            start = max(last + 1, current - settings.SCANNER_RECOVERY_MAX_SLOTS)
            abandoned = start - (last + 1)
            self.stats.recovery_runs += 1
            self.stats.recovery_slots_abandoned += abandoned
            logger.info(
                "scanner_recovery_started",
                gap_slots=current - last - 1,
                from_slot=start,
                to_slot=current,
                abandoned_slots=abandoned,
            )

            slots = await self._rpc.call(
                "getBlocks", [start, current, {"commitment": settings.SCANNER_COMMITMENT}]
            )
            if not isinstance(slots, list):
                return

            queued = 0
            scanned = 0
            consecutive_block_failures = 0
            # A wall-clock budget, not just a slot budget. Against a throttled
            # endpoint each block can cost ~90s of retry backoff, so a
            # 1500-slot walk that "should" take six minutes was still running
            # 2.5 hours later — sharing its RPC allowance with live
            # resolution the whole time. Newest-first inside the window would
            # not help: the walk reads oldest-first so a partial walk covers a
            # contiguous prefix, and the deadline bounds the total spend.
            deadline = time.monotonic() + 15 * 60
            for index, slot in enumerate(slots):
                if self._stop.is_set():
                    break
                if time.monotonic() > deadline:
                    remaining = len(slots) - index
                    self.stats.recovery_slots_abandoned += remaining
                    logger.error(
                        "scanner_recovery_abandoned",
                        reason="wall-clock budget exhausted",
                        slots_abandoned=remaining,
                        slots_scanned=self.stats.recovery_slots_scanned,
                    )
                    break
                try:
                    block = await self._rpc.call(
                        "getBlock",
                        [
                            slot,
                            {
                                "commitment": settings.SCANNER_COMMITMENT,
                                "encoding": "json",
                                "transactionDetails": "full",
                                "rewards": False,
                                "maxSupportedTransactionVersion": 0,
                            },
                        ],
                    )
                except Exception as exc:
                    # One unreadable block costs that block, not the walk —
                    # but a *run* of failures means the endpoint is refusing
                    # getBlock wholesale (public nodes throttle it far harder
                    # than getTransaction). Grinding on would spend hours of
                    # shared RPC budget against a closed door while the live
                    # fallback path competes for the same allowance; abandon
                    # visibly instead. Measured live on 2026-08-20: a 1500-slot
                    # walk against the public endpoint covered ~100 slots in
                    # 2.5 hours before this guard existed.
                    consecutive_block_failures += 1
                    logger.warning(
                        "scanner_recovery_block_failed", slot=slot, error=str(exc)
                    )
                    if consecutive_block_failures >= 10:
                        remaining = len(slots) - index - 1
                        self.stats.recovery_slots_abandoned += remaining + 1
                        logger.error(
                            "scanner_recovery_abandoned",
                            reason="persistent block-fetch failures",
                            slots_abandoned=remaining + 1,
                            slots_scanned=self.stats.recovery_slots_scanned,
                        )
                        break
                    continue

                consecutive_block_failures = 0
                scanned += 1
                self.stats.recovery_slots_scanned += 1
                if isinstance(block, dict):
                    for event in creation_events_from_block(
                        block,
                        slot=int(slot),
                        programs=self._programs,
                        observed_at=datetime.now(UTC),
                    ):
                        await self._queue.put(event)
                        queued += 1
                        # Counted as it happens, not at the end: a walk
                        # cancelled mid-flight has still queued its events.
                        self.stats.recovery_events_queued += 1

                await asyncio.sleep(settings.SCANNER_RECOVERY_BLOCK_DELAY_SECONDS)

            logger.info(
                "scanner_recovery_completed",
                slots_scanned=scanned,
                slots_in_window=len(slots),
                events_queued=queued,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            # Recovery is best-effort on top of a live stream that has already
            # resumed; a failed walk must never take the scanner down with it.
            logger.exception("scanner_recovery_failed")

    async def _subscribe(self, ws: ClientConnection) -> None:
        """Subscribe to every watched program, matching responses by id.

        Two hard-won rules, both from the night PumpSwap watching shipped
        (2026-08-20, discovery fell 10x for nine hours):

        * **Responses must be matched by request id, never by arrival order.**
          The first subscription starts delivering notifications immediately,
          so a blocking `recv` for the second program's response routinely
          reads a notification instead — and the old code declared the
          subscribe failed and tore the connection down, taking the healthy
          pump.fun subscription with it, on every reconnect, indefinitely.
          Notifications read during the handshake are discarded deliberately:
          the recovery walk starts from a slot fetched *after* this method, so
          the discarded window is recovered rather than lost.

        * **A refused secondary subscription must not cost the primary.** The
          public endpoint sometimes rejects the second `logsSubscribe`
          outright; coverage of one launchpad is strictly better than a
          reconnect loop covering none. Only zero successes is fatal.
        """
        self._subscription_programs.clear()
        pending: dict[int, str] = {}
        for index, program in enumerate(self._programs):
            request_id = index + 1
            await ws.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "logsSubscribe",
                        "params": [
                            {"mentions": [program]},
                            {"commitment": settings.SCANNER_COMMITMENT},
                        ],
                    }
                )
            )
            pending[request_id] = program

        subscribed: list[str] = []
        deadline = time.monotonic() + 30.0
        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except TimeoutError:
                break
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(message, dict) or "id" not in message:
                continue  # a notification racing the handshake; recovered later
            response_id = message.get("id")
            if not isinstance(response_id, int) or response_id not in pending:
                continue
            program = pending.pop(response_id)
            subscription = message.get("result")
            if isinstance(subscription, int):
                self._subscription_programs[subscription] = program
                subscribed.append(program)
            else:
                logger.error(
                    "scanner_subscribe_refused",
                    program=program,
                    response=str(message.get("error") or message)[:200],
                    detail=(
                        "Continuing without this program; its launches are "
                        "not being watched."
                    ),
                )

        for program in pending.values():
            logger.error(
                "scanner_subscribe_refused",
                program=program,
                response="no response within 30s",
                detail="Continuing without this program; its launches are not being watched.",
            )

        if not subscribed:
            raise RuntimeError("logsSubscribe failed for every watched program")
        logger.info("scanner_subscribed", programs=subscribed)

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
            if event is None:
                continue

            # Wallet flow, before the creation pre-filter: a trade is not a
            # creation, so anything gated behind that filter would never see
            # one. Wrapped because observation must never be able to stop
            # discovery — the same rule the research ledger follows.
            if self._flow is not None:
                try:
                    self._record_trades(event)
                except Exception:
                    self._flow_decode_failures += 1
            # Every notification advances the gap marker, not just creations:
            # the stream is mostly trades, which is what makes it a dense clock.
            if event.slot > (self._last_slot or 0):
                self._last_slot = event.slot
            if not is_token_creation_log(event.logs):
                continue

            subscription = (message.get("params") or {}).get("subscription")
            if not isinstance(subscription, int):
                logger.warning("scanner_unknown_subscription", subscription=subscription)
                continue
            program = self._subscription_programs.get(subscription)
            # A notification without a known subscription cannot be assigned a
            # provenance program honestly. Do not make it look like Pump.fun.
            if program is None:
                logger.warning("scanner_unknown_subscription", subscription=subscription)
                continue
            event = LogEvent(
                signature=event.signature,
                slot=event.slot,
                logs=event.logs,
                source_program=program,
                observed_at=datetime.now(UTC),
            )

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

    def _from_logs(self, event: LogEvent) -> _Resolution | None:
        """Resolve a creation from the log payload alone, or None.

        The fast path, and the one that survives a rate limit: the launchpad's
        own creation event carries the mint, the creator and (for pump.fun) the
        token's metadata, so nothing here touches the network. A PumpSwap pool
        creation resolves the same way from its `CreatePoolEvent`; it carries
        no name or symbol, so the token stays `MetadataStatus.PENDING` until
        the metadata step fills it in. `decimals` is only set when an event
        reports it, never assumed.

        The decoder that answered is returned with the result. The ledger's
        `event_type` is provenance, so it must name the path actually taken —
        inferring it afterwards from whether metadata came back non-empty
        mislabels a pump.fun token whose DAS lookup happened to return nothing.
        """
        decoded = parse_create_event(event.logs)
        source = "pumpfun_create_event"
        if decoded is None:
            decoded = parse_pumpswap_pool_event(event.logs)
            source = "pumpswap_create_pool"
        if decoded is None:
            return None

        creation = TokenCreation(
            mint_address=decoded.mint_address,
            signature=event.signature,
            slot=event.slot,
            creator_address=decoded.creator_address,
            decimals=decoded.decimals,
            block_time=decoded.block_time,
            source_program=event.source_program,
        )
        metadata = TokenMetadata(
            name=decoded.name,
            symbol=decoded.symbol,
            metadata_uri=decoded.metadata_uri,
            image_url=None,
            decimals=decoded.decimals,
        )
        return _Resolution(creation=creation, metadata=metadata, event_type=source)

    async def _from_transaction(self, event: LogEvent) -> _Resolution | None:
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
            source_program=event.source_program,
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
        return _Resolution(
            creation=creation, metadata=metadata, event_type="mint_initialization"
        )

    async def _handle_event(self, event: LogEvent) -> None:
        resolved: _Resolution | None = self._from_logs(event)
        if resolved is not None:
            self.stats.resolved_from_logs += 1
        elif any(POOL_CREATE_MARKER in line for line in event.logs):
            # A pool creation whose event did not decode. The transaction
            # fallback is *wrong* here, not merely wasteful: the only mint such
            # a transaction initialises is the pool's LP mint, which
            # `extract_mint_and_decimals` would confidently report as a new
            # token. Refuse the reading; the counter keeps the refusals visible.
            self.stats.pool_events_refused += 1
            logger.warning("pool_event_refused", signature=event.signature)
            return
        else:
            resolved = await self._from_transaction(event)
            if resolved is None:
                return
            self.stats.resolved_from_transaction += 1

        creation, metadata = resolved.creation, resolved.metadata

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
                image_url=metadata.image_url,
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
        # Telemetry is intentionally after the canonical commit and isolated:
        # a research ledger failure must never undo or delay production discovery.
        try:
            await record_rpc_observation(
                DiscoveryEvent(
                    mint_address=creation.mint_address,
                    observed_at=event.observed_at or datetime.now(UTC),
                    slot=creation.slot,
                    signature=creation.signature,
                    source="rpc_ws",
                    program=creation.source_program,
                    # Provenance: which decoder actually answered, decided at
                    # the point of resolution rather than inferred afterwards.
                    event_type=resolved.event_type,
                    provider_timestamp=creation.block_time,
                    ingest_timestamp=datetime.now(UTC),
                    replayed=event.replayed,
                )
            )
        except Exception:
            logger.exception("rpc_discovery_observation_failed", mint=creation.mint_address)
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
        "image_url": token.image_url,
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
