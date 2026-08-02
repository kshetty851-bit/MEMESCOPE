"""WebSocket broadcast tests.

Uses Starlette's TestClient, whose `websocket_connect` runs the app in a worker
thread — the async httpx client cannot speak the WebSocket protocol.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from starlette.testclient import TestClient

from app.core.config import settings

pytestmark = pytest.mark.integration

WS_PATH = f"{settings.API_V1_PREFIX}/tokens/stream"

PAYLOAD = {
    "id": "0f6b1c2e-0000-0000-0000-000000000000",
    "mint_address": "HHbRJ9Fw2tPxETGSsaeQhpgdizfVafLvXK7eo5mwpump",
    "name": "Indian Batman",
    "symbol": "JEETMAN",
    "decimals": 6,
    "metadata_uri": "https://ipfs.io/ipfs/abc",
    "creator_address": "5r1Q8ehbFi4SaF8XLjcNMCdJCEov95wttcmjgk3ncXTr",
    "signature": "sig",
    "slot": 435484419,
    "block_time": "2026-07-27T05:32:21+00:00",
    "discovered_at": "2026-07-27T05:32:25+00:00",
    "source_program": "prog",
    "metadata_status": "resolved",
}


def test_client_receives_ready_frame(app: Any) -> None:
    with TestClient(app) as test_client, test_client.websocket_connect(WS_PATH) as websocket:
        assert websocket.receive_json()["type"] == "connection.ready"


def test_discovery_is_broadcast_to_connected_client(app: Any) -> None:
    """An event published to Redis must reach a live WebSocket client."""
    import redis as sync_redis

    with TestClient(app) as test_client, test_client.websocket_connect(WS_PATH) as websocket:
        assert websocket.receive_json()["type"] == "connection.ready"

        publisher = sync_redis.Redis(
            host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB
        )
        # Retry briefly: the broadcaster subscribes asynchronously, and a
        # publish that lands before SUBSCRIBE completes reaches nobody.
        for _ in range(40):
            publisher.publish(settings.token_channel, json.dumps(PAYLOAD))
            message = websocket.receive_json()
            if message["type"] == "token.discovered":
                assert message["data"]["mint_address"] == PAYLOAD["mint_address"]
                assert message["data"]["symbol"] == "JEETMAN"
                publisher.close()
                return
        publisher.close()
        raise AssertionError("discovery was never delivered to the WebSocket client")


def test_malformed_event_does_not_kill_the_stream(app: Any) -> None:
    import redis as sync_redis

    with TestClient(app) as test_client, test_client.websocket_connect(WS_PATH) as websocket:
        assert websocket.receive_json()["type"] == "connection.ready"

        publisher = sync_redis.Redis(
            host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB
        )
        publisher.publish(settings.token_channel, "this is not json")

        for _ in range(40):
            publisher.publish(settings.token_channel, json.dumps(PAYLOAD))
            message = websocket.receive_json()
            if message["type"] == "token.discovered":
                publisher.close()
                return
        publisher.close()
        raise AssertionError("stream did not recover after a malformed event")
