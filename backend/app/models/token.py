"""Discovered SPL token model.

One row per mint. `mint_address` is the natural key and carries a unique
constraint, which is what makes ingestion idempotent: the scanner can replay the
same event any number of times and the insert collapses to a no-op.

Two timestamps are kept deliberately:
  * `block_time`    — when the token was created on-chain.
  * `discovered_at` — when this system first saw it.
The gap between them is our ingestion latency, and it is worth being able to
measure rather than infer.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# Base58 encodes 32-byte keys to 32-44 characters.
PUBKEY_MAX_LENGTH = 44
SIGNATURE_MAX_LENGTH = 88


class MetadataStatus(enum.StrEnum):
    """Lifecycle of off-chain metadata resolution.

    A token is recorded the moment it is detected, even when its metadata has
    not been indexed yet — losing the discovery would be far worse than storing
    a row whose name arrives a few seconds later.
    """

    PENDING = "pending"
    RESOLVED = "resolved"
    FAILED = "failed"


class DiscoveredToken(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "discovered_tokens"

    mint_address: Mapped[str] = mapped_column(
        String(PUBKEY_MAX_LENGTH), unique=True, index=True, nullable=False
    )

    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decimals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_uri: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    creator_address: Mapped[str | None] = mapped_column(
        String(PUBKEY_MAX_LENGTH), index=True, nullable=True
    )

    signature: Mapped[str] = mapped_column(
        String(SIGNATURE_MAX_LENGTH), index=True, nullable=False
    )
    # Slots exceed the 32-bit integer range, so BigInteger is not optional here.
    slot: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)

    block_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, nullable=True
    )
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )

    # Which watched program the discovery came from (e.g. the pump.fun program id).
    source_program: Mapped[str | None] = mapped_column(
        String(PUBKEY_MAX_LENGTH), index=True, nullable=True
    )

    metadata_status: Mapped[MetadataStatus] = mapped_column(
        Enum(
            MetadataStatus,
            name="metadata_status",
            native_enum=True,
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=MetadataStatus.PENDING,
        server_default=MetadataStatus.PENDING.value,
        nullable=False,
    )
    metadata_attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    __table_args__ = (
        # The live feed is "newest first", and the retry sweep looks up pending
        # rows by age; both are covered here.
        Index("ix_discovered_tokens_discovered_at_desc", discovered_at.desc()),
        Index("ix_discovered_tokens_status_discovered", "metadata_status", "discovered_at"),
    )

    @property
    def is_metadata_resolved(self) -> bool:
        return self.metadata_status is MetadataStatus.RESOLVED
