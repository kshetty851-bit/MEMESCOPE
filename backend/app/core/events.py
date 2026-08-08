"""Cross-process event fan-out for committed live updates.

The scanner runs as its own process and the API runs as N gunicorn workers, so
an in-memory callback list would only ever reach clients that happened to be
connected to the publishing process. Redis pub/sub carries the event to every
API process, and each process fans it out to its own WebSocket clients.

    scanner ──publish──▶ Redis channel ──▶ every API process ──▶ its WS clients

Each subscriber gets its own bounded queue. A client too slow to keep up has
messages dropped rather than being allowed to grow a queue without limit — a
live feed is only useful when it is live, and stale backlog helps nobody.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

from redis.asyncio import Redis

from app.core.config import settings
from app.core.logging import get_logger
from app.core.redis import get_redis

logger = get_logger(__name__)

SUBSCRIBER_QUEUE_SIZE = 100


async def publish_token_discovered(
    payload: dict[str, Any], *, redis: Redis | None = None
) -> int:
    """Publish a discovery. Returns the number of Redis subscribers reached."""
    client = redis or get_redis()
    receivers = await client.publish(settings.token_channel, json.dumps(payload, default=str))
    return int(receivers)


async def publish_score_changed(payload: dict[str, Any], *, redis: Redis | None = None) -> int:
    """Publish a materially changed score.

    Its own channel rather than the discovery one: a score change is not a
    discovery, and multiplexing them would force every consumer to discriminate
    on payload shape before it could tell what it had received.

    Callers must publish **after** the transaction commits. Publishing first
    would let an event describe a score that never landed, and the Observatory
    Log would narrate an event with no row behind it - the same ordering the
    scanner already follows.
    """
    client = redis or get_redis()
    receivers = await client.publish(settings.score_channel, json.dumps(payload, default=str))
    return int(receivers)


async def publish_score_events(
    payloads: Sequence[dict[str, Any]], *, redis: Redis | None = None
) -> int:
    """Publish a batch of score events, best-effort.

    Delivery failures are logged and swallowed: the database is the source of
    truth and the sweep will re-evaluate regardless, so a dropped event costs a
    live update, not correctness. Alerts (Day 8) must therefore read state
    rather than rely on having seen every event.
    """
    delivered = 0
    for payload in payloads:
        try:
            await publish_score_changed(payload, redis=redis)
            delivered += 1
        except Exception as exc:
            logger.warning(
                "score_event_publish_failed",
                mint=payload.get("mint_address"),
                error=str(exc),
            )
    return delivered


async def publish_live_update(
    event_type: str,
    *,
    mints: Sequence[str] = (),
    redis: Redis | None = None,
) -> int:
    """Publish a committed UI invalidation through the existing Redis bus.

    The browser receives identifiers, not another copy of market/business
    values. It refetches the affected server-owned read model, which keeps one
    API response as the authority for every rendered value.
    """
    payload = {"type": event_type, "mints": list(dict.fromkeys(mints))}
    client = redis or get_redis()
    try:
        receivers = await client.publish(settings.live_channel, json.dumps(payload))
    except Exception as exc:
        # The database is already committed. A dropped browser wake-up must not
        # fail enrichment or turn a Redis outage into lost market evidence.
        logger.warning("live_event_publish_failed", event_type=event_type, error=str(exc))
        return 0
    return int(receivers)


class LiveEventBroadcaster:
    """Per-process bridge from Redis topics to one multiplexed WebSocket stream.

    One Redis subscription per process regardless of client count; connecting a
    thousand WebSockets does not open a thousand Redis connections.
    """

    def __init__(self) -> None:
        self._channels = {
            settings.token_channel: "token.discovered",
            settings.score_channel: "score.changed",
            settings.live_channel: None,
        }
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def start(self) -> None:
        async with self._lock:
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._listen(), name="token-event-listener")
                logger.info("live_broadcaster_started", channels=list(self._channels))

    async def stop(self) -> None:
        async with self._lock:
            if self._task is not None:
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._task
                self._task = None
        self._subscribers.clear()
        logger.info("live_broadcaster_stopped")

    async def _listen(self) -> None:
        """Consume the Redis channel forever, reconnecting on failure."""
        attempt = 0
        while True:
            pubsub = None
            try:
                pubsub = get_redis().pubsub()
                await pubsub.subscribe(*self._channels)
                attempt = 0
                logger.info("live_broadcaster_subscribed", channels=list(self._channels))

                async for message in pubsub.listen():
                    if message.get("type") != "message":
                        continue
                    try:
                        payload = json.loads(message["data"])
                    except (ValueError, TypeError):
                        logger.warning(
                            "live_event_malformed", raw=str(message.get("data"))[:200]
                        )
                        continue
                    channel = message.get("channel")
                    if isinstance(channel, bytes):
                        channel = channel.decode()
                    kind = self._channels.get(channel)
                    if kind is None and channel != settings.live_channel:
                        logger.warning("live_event_unknown_channel", channel=str(channel))
                        continue
                    if kind is None:
                        valid_event = isinstance(payload, dict) and isinstance(
                            payload.get("type"), str
                        )
                        if not valid_event:
                            logger.warning(
                                "live_event_malformed", raw=str(message.get("data"))[:200]
                            )
                            continue
                        event = payload
                    else:
                        event = {"type": kind, "data": payload}
                    self._fan_out(event)

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                attempt += 1
                delay = min(2.0**attempt, 30.0)
                logger.warning(
                    "live_broadcaster_reconnect",
                    error=str(exc),
                    attempt=attempt,
                    delay_seconds=delay,
                )
                await asyncio.sleep(delay)
            finally:
                if pubsub is not None:
                    with contextlib.suppress(Exception):
                        await pubsub.aclose()  # type: ignore[no-untyped-call]

    def _fan_out(self, payload: dict[str, Any]) -> None:
        dropped = 0
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                dropped += 1
        if dropped:
            logger.warning("token_event_dropped_slow_consumer", dropped=dropped)

    @contextlib.asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        """Register a queue for the lifetime of one WebSocket connection."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        self._subscribers.add(queue)
        await self.start()
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)


broadcaster = LiveEventBroadcaster()
