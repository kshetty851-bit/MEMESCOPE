"""Append-only discovery source observations and durable stream checkpoints."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class DiscoveryObservationSource(enum.StrEnum):
    RPC_WS = "rpc_ws"
    YELLOWSTONE_GRPC = "yellowstone_grpc"


class DiscoverySourceObservation(Base, UUIDPrimaryKeyMixin):
    """An immutable parsed creation seen by one discovery transport.

    It intentionally has no foreign key to ``discovered_tokens``: Yellowstone
    shadow observations must remain recordable even when the canonical scanner
    has not (or never will) insert the mint.
    """

    __tablename__ = "discovery_source_observations"

    source: Mapped[DiscoveryObservationSource] = mapped_column(
        String(32), nullable=False, index=True
    )
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)
    signature: Mapped[str] = mapped_column(String(88), nullable=False)
    slot: Mapped[int] = mapped_column(BigInteger, nullable=False)
    program: Mapped[str | None] = mapped_column(String(44), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Local wall clock at source socket receive, the comparison clock.
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Source-provided timestamp (Yellowstone ``created_at`` or parsed chain event).
    provider_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    replayed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    reconnect_generation: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    provider_sequence: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "source", "signature", "mint_address", name="uq_discovery_observation"
        ),
        Index("ix_discovery_observation_mint_observed", "mint_address", "observed_at"),
        Index("ix_discovery_observation_source_slot", "source", "slot"),
    )


class YellowstoneStreamCheckpoint(Base):
    """One durable checkpoint for the non-authoritative Yellowstone stream."""

    __tablename__ = "yellowstone_stream_checkpoints"

    stream_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_durable_slot: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_durable_signature: Mapped[str | None] = mapped_column(String(88), nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_received_slot: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reconnect_generation: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    messages_received: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    matching_pumpfun_events: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    unique_mints: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    duplicates: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    replays: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    errors: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    connected: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
