"""Live event publication failure handling."""

from __future__ import annotations

import pytest

from app.core import events

pytestmark = pytest.mark.unit


async def test_live_update_publish_failure_is_non_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Redis outage must not fail a committed paper review."""

    def _missing_redis() -> object:
        raise RuntimeError("Redis is not initialised. Did the lifespan hook run?")

    monkeypatch.setattr(events, "get_redis", _missing_redis)

    assert await events.publish_live_update("paper.changed") == 0
