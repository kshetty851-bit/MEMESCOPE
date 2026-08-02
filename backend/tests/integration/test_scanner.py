"""Scanner tests.

The Helius WebSocket and RPC are replaced with fakes so the full pipeline —
filter, resolve, persist, broadcast — runs deterministically and offline. What
is exercised here is the scanner's own logic, not Helius.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.token import DiscoveredToken, MetadataStatus
from app.services.scanner.scanner import TokenScanner

pytestmark = pytest.mark.integration

MINT = "HHbRJ9Fw2tPxETGSsaeQhpgdizfVafLvXK7eo5mwpump"
CREATOR = "5r1Q8ehbFi4SaF8XLjcNMCdJCEov95wttcmjgk3ncXTr"
SIG = (
    "5APdFocxZdDUbHAU5vyEtSR9gWm21ftvRMh1WHr4ZUNxN38ZGiF3fBAMfLBcThTtkgQVH5NeGQxXxZ9LpXMJDG7g"
)


def _notification(signature: str = SIG) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "logsNotification",
            "params": {
                "result": {
                    "context": {"slot": 435484419},
                    "value": {
                        "signature": signature,
                        "err": None,
                        "logs": [
                            "Program 6EF8rrec invoke [1]",
                            "Program log: Instruction: CreateV2",
                            "Program log: Instruction: InitializeMint2",
                        ],
                    },
                }
            },
        }
    )


def _transaction() -> dict[str, Any]:
    return {
        "slot": 435484419,
        "blockTime": 1785132741,
        "meta": {
            "err": None,
            "innerInstructions": [
                {
                    "instructions": [
                        {
                            "parsed": {
                                "type": "initializeMint2",
                                "info": {"decimals": 6, "mint": MINT},
                            }
                        }
                    ]
                }
            ],
            "preTokenBalances": [],
            "postTokenBalances": [{"mint": MINT}],
        },
        "transaction": {"message": {"accountKeys": [{"pubkey": CREATOR}], "instructions": []}},
    }


class FakeHelius:
    """Stands in for HeliusClient. Records calls so retries are observable."""

    def __init__(self, *, asset: dict[str, Any] | None = None, transaction: Any = "default"):
        self.asset = asset
        self._transaction = _transaction() if transaction == "default" else transaction
        self.transaction_calls: list[str] = []
        self.asset_calls: list[str] = []

    async def start(self) -> None: ...
    async def close(self) -> None: ...

    async def get_transaction(self, signature: str, **_: Any) -> dict[str, Any] | None:
        self.transaction_calls.append(signature)
        return self._transaction

    async def get_asset(self, mint: str, **_: Any) -> dict[str, Any] | None:
        self.asset_calls.append(mint)
        return self.asset


RESOLVED_ASSET = {
    "content": {
        "json_uri": "https://ipfs.io/ipfs/abc",
        "metadata": {"name": "Indian Batman", "symbol": "JEETMAN"},
    },
    "token_info": {"decimals": 6},
}


@pytest.fixture(autouse=True)
async def _clear_dedupe(client: Any) -> Any:
    """Redis dedupe keys are global; clear them so tests do not leak into each other."""
    from app.core.redis import get_redis

    await get_redis().flushdb()
    yield
    await get_redis().flushdb()


async def _run_one_event(scanner: TokenScanner, payload: str) -> None:
    message = json.loads(payload)
    from app.services.scanner.parser import is_token_creation_log, parse_log_notification

    event = parse_log_notification(message)
    assert event is not None
    assert is_token_creation_log(event.logs)
    await scanner._handle_event(event)


async def test_discovers_persists_and_broadcasts(db_session: Any, client: Any) -> None:
    helius = FakeHelius(asset=RESOLVED_ASSET)
    scanner = TokenScanner(helius=helius, ws_url="ws://fake", programs=["prog"])

    received: list[dict[str, Any]] = []
    from app.core.redis import get_redis

    pubsub = get_redis().pubsub()
    await pubsub.subscribe(settings.token_channel)

    await _run_one_event(scanner, _notification())

    # Drain the pub/sub channel.
    for _ in range(10):
        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
        if message:
            received.append(json.loads(message["data"]))
            break
    await pubsub.aclose()

    assert scanner.stats.tokens_discovered == 1

    from app.db.session import SessionFactory

    async with SessionFactory() as session:
        row = (
            (
                await session.execute(
                    select(DiscoveredToken).where(DiscoveredToken.mint_address == MINT)
                )
            )
            .scalars()
            .first()
        )
        assert row is not None
        assert row.name == "Indian Batman"
        assert row.symbol == "JEETMAN"
        assert row.decimals == 6
        assert row.creator_address == CREATOR
        assert row.metadata_status is MetadataStatus.RESOLVED
        await session.delete(row)
        await session.commit()

    assert received, "discovery must be published to the event channel"
    assert received[0]["mint_address"] == MINT


async def test_duplicate_event_is_suppressed(db_session: Any, client: Any) -> None:
    """The same event replayed must not produce a second row or broadcast."""
    helius = FakeHelius(asset=RESOLVED_ASSET)
    scanner = TokenScanner(helius=helius, ws_url="ws://fake", programs=["prog"])

    await _run_one_event(scanner, _notification())
    await _run_one_event(scanner, _notification())

    assert scanner.stats.tokens_discovered == 1
    assert scanner.stats.tokens_duplicate == 1

    from app.db.session import SessionFactory

    async with SessionFactory() as session:
        rows = (
            (
                await session.execute(
                    select(DiscoveredToken).where(DiscoveredToken.mint_address == MINT)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        for row in rows:
            await session.delete(row)
        await session.commit()


async def test_missing_metadata_is_saved_as_pending(db_session: Any, client: Any) -> None:
    """A token with no metadata yet must still be recorded, not dropped."""
    scanner = TokenScanner(
        helius=FakeHelius(asset=None), ws_url="ws://fake", programs=["prog"]
    )
    await _run_one_event(scanner, _notification())

    from app.db.session import SessionFactory

    async with SessionFactory() as session:
        row = (
            (
                await session.execute(
                    select(DiscoveredToken).where(DiscoveredToken.mint_address == MINT)
                )
            )
            .scalars()
            .first()
        )
        assert row is not None
        assert row.metadata_status is MetadataStatus.PENDING
        assert row.name is None
        # The mint itself was still captured, which is the important part.
        assert row.decimals == 6
        await session.delete(row)
        await session.commit()

    assert scanner.stats.tokens_discovered == 1


async def test_unavailable_transaction_is_counted_not_crashed(client: Any) -> None:
    scanner = TokenScanner(
        helius=FakeHelius(transaction=None), ws_url="ws://fake", programs=["prog"]
    )
    await _run_one_event(scanner, _notification())

    assert scanner.stats.tokens_discovered == 0
    assert scanner.stats.resolve_failures == 1


async def test_queue_overflow_drops_instead_of_blocking(client: Any) -> None:
    """Under a launch burst the scanner sheds load rather than stalling the socket."""
    scanner = TokenScanner(helius=FakeHelius(), ws_url="ws://fake", programs=["prog"])
    scanner._queue = asyncio.Queue(maxsize=2)

    class FakeSocket:
        def __init__(self, count: int) -> None:
            self._messages = [_notification(f"sig{i}") for i in range(count)]

        async def recv(self) -> str:
            if not self._messages:
                raise asyncio.CancelledError
            return self._messages.pop(0)

    with pytest.raises(asyncio.CancelledError):
        await scanner._consume(FakeSocket(6))

    assert scanner.stats.events_queued == 2
    assert scanner.stats.events_dropped == 4


async def test_non_creation_logs_are_filtered_out(client: Any) -> None:
    scanner = TokenScanner(helius=FakeHelius(), ws_url="ws://fake", programs=["prog"])

    noise = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "logsNotification",
            "params": {
                "result": {
                    "context": {"slot": 1},
                    "value": {
                        "signature": "noise",
                        "err": None,
                        "logs": ["Program log: Instruction: TransferChecked"],
                    },
                }
            },
        }
    )

    class FakeSocket:
        def __init__(self) -> None:
            self._sent = False

        async def recv(self) -> str:
            if self._sent:
                raise asyncio.CancelledError
            self._sent = True
            return noise

    with pytest.raises(asyncio.CancelledError):
        await scanner._consume(FakeSocket())

    assert scanner.stats.events_received == 1
    assert scanner.stats.events_filtered == 0
    assert scanner.stats.events_queued == 0
