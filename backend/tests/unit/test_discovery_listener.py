"""One bad discovery message must never cost the subscription.

Before this, only JSON errors were caught per-message; anything the database
raised escaped to the reconnect handler and tore down the whole pub/sub
subscription. A single message naming a token that did not exist — exactly what
a test run publishing onto a shared channel produced — stopped every subsequent
discovery until the resubscribe completed, then repeated.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.services.market.worker import MarketEnrichmentWorker

pytestmark = pytest.mark.unit


class _StubProvider:
    name = "stub"

    async def fetch_many(self, mints: list[str]) -> dict[str, Any]:
        return {}

    async def close(self) -> None:
        return None


@pytest.fixture
def worker() -> MarketEnrichmentWorker:
    return MarketEnrichmentWorker(provider=_StubProvider())  # type: ignore[arg-type]


def _message(payload: Any) -> dict[str, Any]:
    return {"type": "message", "data": json.dumps(payload)}


class TestMalformedPayloads:
    @pytest.mark.parametrize(
        "data",
        [
            "not json at all",
            "[1, 2, 3]",
            "null",
            '{"no_mint": true}',
            '{"mint_address": ""}',
            '{"mint_address": null}',
        ],
    )
    async def test_malformed_messages_are_counted_and_survived(
        self, worker: MarketEnrichmentWorker, data: str
    ) -> None:
        await worker._handle_discovery_message({"type": "message", "data": data})

        assert worker.stats.discovery_messages == 1
        assert worker.stats.discovery_messages_failed == 1
        # The listener never learns about it: no exception escapes.

    async def test_a_message_with_no_data_key_does_not_raise(
        self, worker: MarketEnrichmentWorker
    ) -> None:
        await worker._handle_discovery_message({"type": "message"})
        assert worker.stats.discovery_messages_failed == 1


class TestDatabaseFailures:
    async def test_a_database_error_is_isolated_to_that_message(
        self, worker: MarketEnrichmentWorker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The exact production failure: a foreign key violation.

        It must be counted and swallowed, not raised into the listener loop.
        """

        class _Boom:
            def __call__(self, *args: Any, **kwargs: Any) -> Any:
                raise RuntimeError("ForeignKeyViolationError: token_id not present")

        monkeypatch.setattr("app.services.market.worker.SessionFactory", _Boom())

        await worker._handle_discovery_message(
            _message({"mint_address": "HHbRJ9Fw2tPxETGSsaeQhpgdizfVafLvXK7eo5mwpump"})
        )

        assert worker.stats.discovery_messages_failed == 1
        assert worker.stats.listener_reconnects == 0

    async def test_the_listener_keeps_processing_after_a_poison_message(
        self, worker: MarketEnrichmentWorker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A run of bad messages must not stop good ones being handled.

        This is the whole point: blast radius of one message is one message.
        """
        calls: list[str] = []

        class _Session:
            async def __aenter__(self) -> _Session:
                return self

            async def __aexit__(self, *args: Any) -> None:
                return None

            async def commit(self) -> None:
                return None

        class _Service:
            def __init__(self, *args: Any, **kwargs: Any) -> None: ...

            async def register_token(self, mint: str) -> bool:
                calls.append(mint)
                if mint.startswith("bad"):
                    raise RuntimeError("ForeignKeyViolationError")
                return True

        monkeypatch.setattr("app.services.market.worker.SessionFactory", lambda: _Session())
        monkeypatch.setattr("app.services.market.worker.MarketEnrichmentService", _Service)

        for mint in ["bad-one", "good-one", "bad-two", "good-two"]:
            await worker._handle_discovery_message(_message({"mint_address": mint}))

        assert calls == ["bad-one", "good-one", "bad-two", "good-two"]
        assert worker.stats.discovery_messages == 4
        assert worker.stats.discovery_messages_failed == 2
        assert worker.stats.tokens_registered == 2

    async def test_cancellation_is_never_swallowed(
        self, worker: MarketEnrichmentWorker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Shutdown must still be able to stop the worker.

        A blanket `except Exception` that also caught CancelledError would make
        the listener unkillable.
        """
        import asyncio

        class _Boom:
            def __call__(self, *args: Any, **kwargs: Any) -> Any:
                raise asyncio.CancelledError

        monkeypatch.setattr("app.services.market.worker.SessionFactory", _Boom())

        with pytest.raises(asyncio.CancelledError):
            await worker._handle_discovery_message(_message({"mint_address": "any"}))


class TestCounters:
    async def test_successful_messages_are_counted_but_not_as_failures(
        self, worker: MarketEnrichmentWorker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _Session:
            async def __aenter__(self) -> _Session:
                return self

            async def __aexit__(self, *args: Any) -> None:
                return None

            async def commit(self) -> None:
                return None

        class _Service:
            def __init__(self, *args: Any, **kwargs: Any) -> None: ...

            async def register_token(self, mint: str) -> bool:
                return True

        monkeypatch.setattr("app.services.market.worker.SessionFactory", lambda: _Session())
        monkeypatch.setattr("app.services.market.worker.MarketEnrichmentService", _Service)

        await worker._handle_discovery_message(_message({"mint_address": "mint-1"}))

        assert worker.stats.discovery_messages == 1
        assert worker.stats.discovery_messages_failed == 0
        assert worker.stats.tokens_registered == 1
        assert "discovery_messages_failed" in worker.stats.as_dict()
