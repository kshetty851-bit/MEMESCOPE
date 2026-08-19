"""Normalized, source-neutral token-discovery events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

DiscoverySource = Literal["rpc_ws", "yellowstone_grpc"]


@dataclass(frozen=True, slots=True)
class DiscoveryEvent:
    """A parsed token creation observed by one transport.

    ``observed_at`` is the local source-receipt time.  It is deliberately
    distinct from the optional provider/on-chain timestamp and from the time a
    row reaches Postgres, so latency comparisons never conflate three clocks.
    """

    mint_address: str
    observed_at: datetime
    slot: int
    signature: str
    source: DiscoverySource
    program: str | None
    event_type: str
    provider_timestamp: datetime | None = None
    ingest_timestamp: datetime | None = None
    replayed: bool = False
    reconnect_generation: int = 0
    provider_sequence: int | None = None

    def __post_init__(self) -> None:
        if not self.mint_address or not self.signature:
            raise ValueError("discovery event requires mint_address and signature")
        if self.slot < 0:
            raise ValueError("discovery event slot cannot be negative")
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")

    @property
    def ingested_at(self) -> datetime:
        return self.ingest_timestamp or datetime.now(UTC)
