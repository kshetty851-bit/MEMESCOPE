"""Health probes and baseline response plumbing."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration


async def test_liveness_is_ok(client: AsyncClient) -> None:
    response = await client.get("/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_readiness_reports_dependencies(client: AsyncClient) -> None:
    response = await client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["checks"]["database"]["status"] == "ok"
    assert body["checks"]["redis"]["status"] == "ok"


async def test_every_response_carries_a_request_id(client: AsyncClient) -> None:
    response = await client.get("/live")
    assert response.headers["X-Request-ID"]


async def test_upstream_request_id_is_preserved(client: AsyncClient) -> None:
    response = await client.get("/live", headers={"X-Request-ID": "trace-abc-123"})
    assert response.headers["X-Request-ID"] == "trace-abc-123"


async def test_security_headers_are_applied(client: AsyncClient) -> None:
    response = await client.get("/live")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


async def test_unknown_route_uses_the_error_envelope(client: AsyncClient) -> None:
    response = await client.get("/nope")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["request_id"]
