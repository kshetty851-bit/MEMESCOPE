"""Yellowstone Phase 1 is an observational stream, never canonical discovery."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.discovery import DiscoverySourceObservation, YellowstoneStreamCheckpoint
from app.models.paper import PaperPosition
from app.models.radar import RadarToken
from app.models.token import DiscoveredToken
from app.services.discovery.yellowstone import (
    YellowstoneShadowProvider,
    YellowstoneTransaction,
    filtered_pumpfun_subscription,
)

pytestmark = pytest.mark.integration

MINT = "HHbRJ9Fw2tPxETGSsaeQhpgdizfVafLvXK7eo5mwpump"
SIG = "".join(
    (
        "5APdFocxZdDUbHAU5vyEtSR9gWm21ftvRMh1WHr4ZUNxN38ZGiF3fBAMfLBcThTt",
        "kgQVH5NeGQxXxZ9LpXMJDG7g",
    )
)
REAL_EVENT = (
    "Program data: G3KpTd7rY3YFAAAAc2VhbHkFAAAAc2VhbHlDAAAAaHR0cHM6Ly9pcGZzLmlvL2lwZnMv"
    "UW1YUk5TRDJmc3FncTFGdGZLSHhKSmdvWXZiNVBSeURoS3NqTlFGNFZvTFFFUEDWXWT6DfE70ocWan1n"
    "rbUMoU8ME79LnAoD0j4+7lEZ5xUTUm01m0qqkuwnqleIXH//r+1i72hHe0dsFbt4pEXS8/oqVRM/opM2"
    "XoQYgyk8FrKL8y8OlLoQOlt2GbTLuNLz+ipVEz+ikzZehBiDKTwWsovzLw6UuhA6W3YZtMu4d+BwagAA"
    "AAAAENhH488DAACsI/wGAAAAAHjF+1HRAgAAgMakfo0DAAbd9uHudY/eGEJdvORszdq2GvxNg7kNJ/69"
    "+SjYoYv8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACsI/wGAAAA"
)


def _create_log() -> tuple[str, ...]:
    # No verified CreateEvent payload: this is intentionally not parsed by the
    # direct decoder, so real protocol fixtures must carry captured bytes.
    return ("Program log: Instruction: InitializeMint2",)


def _signature() -> str:
    """Use isolated source-observation keys because worker sessions commit."""
    return uuid4().hex


def test_filtered_subscription_is_confirmed_pumpfun_only() -> None:
    from app.services.discovery.generated import geyser_pb2

    request = filtered_pumpfun_subscription(geyser_pb2, from_slot=321)
    assert request.commitment == geyser_pb2.CONFIRMED
    assert request.from_slot == 321
    assert list(request.transactions) == ["pumpfun"]
    transaction_filter = request.transactions["pumpfun"]
    assert transaction_filter.vote is False
    assert transaction_filter.failed is False
    assert list(transaction_filter.account_include)


async def _provider(
    monkeypatch: pytest.MonkeyPatch, factory: Any
) -> YellowstoneShadowProvider:
    monkeypatch.setattr("app.services.discovery.ledger.SessionFactory", factory)
    monkeypatch.setattr("app.services.discovery.yellowstone.SessionFactory", factory)
    return YellowstoneShadowProvider(transport=_NeverTransport())


class _NeverTransport:
    async def first_available_slot(self) -> int | None:
        return None

    async def stream(self, *, from_slot: int | None):
        if False:
            yield None

    async def close(self) -> None: ...


async def test_shadow_malformed_or_non_create_event_never_writes_canonical(
    db_session: Any, test_session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = await _provider(monkeypatch, test_session_factory)
    await provider._handle(
        YellowstoneTransaction(_signature(), 123, _create_log(), datetime.now(UTC)),
        replayed=False,
    )
    assert provider.stats.messages_received == 1
    assert provider.stats.matching_pumpfun_events == 0
    assert (await db_session.scalars(select(DiscoveredToken))).all() == []
    assert (await db_session.scalars(select(DiscoverySourceObservation))).all() == []
    assert (await db_session.scalars(select(RadarToken))).all() == []
    assert (await db_session.scalars(select(PaperPosition))).all() == []
    checkpoint = await db_session.get(YellowstoneStreamCheckpoint, "pumpfun")
    assert checkpoint is not None
    assert checkpoint.messages_received == 1
    assert checkpoint.matching_pumpfun_events == 0
    assert checkpoint.last_received_slot == 123


async def test_shadow_observation_is_idempotent_and_advances_checkpoint_only_when_saved(
    db_session: Any, test_session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.discovery.events import DiscoveryEvent
    from app.services.discovery.ledger import record_yellowstone_observation

    monkeypatch.setattr("app.services.discovery.ledger.SessionFactory", test_session_factory)
    now = datetime.now(UTC)
    signature = _signature()
    event = DiscoveryEvent(
        mint_address=MINT,
        observed_at=now,
        slot=123,
        signature=signature,
        source="yellowstone_grpc",
        program="pump",
        event_type="pumpfun_create_event",
        replayed=True,
    )
    assert await record_yellowstone_observation(event)
    assert not await record_yellowstone_observation(event)
    rows = (
        await db_session.scalars(
            select(DiscoverySourceObservation).where(
                DiscoverySourceObservation.signature == signature
            )
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].replayed is True
    checkpoint = await db_session.get(YellowstoneStreamCheckpoint, "pumpfun")
    assert checkpoint is not None
    assert checkpoint.last_durable_slot == 123
    assert (await db_session.scalars(select(DiscoveredToken))).all() == []


async def test_yellowstone_pumpfun_create_event_is_saved_only_to_shadow_ledger(
    db_session: Any, test_session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = await _provider(monkeypatch, test_session_factory)
    signature = _signature()
    await provider._handle(
        YellowstoneTransaction(signature, 124, (REAL_EVENT,), datetime.now(UTC), sequence=2),
        replayed=False,
    )
    row = (
        await db_session.scalars(
            select(DiscoverySourceObservation).where(
                DiscoverySourceObservation.signature == signature
            )
        )
    ).one()
    assert row.mint_address
    assert str(row.source) == "yellowstone_grpc"
    assert row.provider_sequence == 2
    assert provider.stats.unique_mints == 1
    assert (await db_session.scalars(select(DiscoveredToken))).all() == []


async def test_source_overlap_keeps_two_telemetry_rows_and_zero_canonical_rows(
    db_session: Any, test_session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.discovery.events import DiscoveryEvent
    from app.services.discovery.ledger import (
        record_rpc_observation,
        record_yellowstone_observation,
    )

    monkeypatch.setattr("app.services.discovery.ledger.SessionFactory", test_session_factory)
    now = datetime.now(UTC)
    signature = _signature()
    common = {
        "mint_address": MINT,
        "observed_at": now,
        "slot": 123,
        "signature": signature,
        "program": "pump",
        "event_type": "create",
    }
    assert await record_yellowstone_observation(
        DiscoveryEvent(source="yellowstone_grpc", **common)
    )
    assert await record_rpc_observation(DiscoveryEvent(source="rpc_ws", **common))
    rows = (
        await db_session.scalars(
            select(DiscoverySourceObservation).where(
                DiscoverySourceObservation.signature == signature
            )
        )
    ).all()
    assert {str(row.source) for row in rows} == {"rpc_ws", "yellowstone_grpc"}
    assert (await db_session.scalars(select(DiscoveredToken))).all() == []


async def test_replay_uses_overlapping_checkpoint_without_duplicate_observation(
    db_session: Any, test_session_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.discovery.events import DiscoveryEvent
    from app.services.discovery.ledger import record_yellowstone_observation

    monkeypatch.setattr("app.services.discovery.ledger.SessionFactory", test_session_factory)
    signature = _signature()
    event = DiscoveryEvent(
        mint_address=MINT,
        observed_at=datetime.now(UTC),
        slot=500,
        signature=signature,
        source="yellowstone_grpc",
        program="pump",
        event_type="pumpfun_create_event",
        replayed=False,
    )
    assert await record_yellowstone_observation(event)
    provider = await _provider(monkeypatch, test_session_factory)
    checkpoint = await db_session.get(YellowstoneStreamCheckpoint, "pumpfun")
    assert checkpoint is not None
    assert provider._replay_slot(checkpoint) == 498
    assert not await record_yellowstone_observation(
        DiscoveryEvent(
            mint_address=MINT,
            observed_at=datetime.now(UTC),
            slot=500,
            signature=signature,
            source="yellowstone_grpc",
            program="pump",
            event_type="pumpfun_create_event",
            replayed=True,
        )
    )
    rows = (
        await db_session.scalars(
            select(DiscoverySourceObservation).where(
                DiscoverySourceObservation.signature == signature
            )
        )
    ).all()
    assert len(rows) == 1
