"""Response models for `GET /api/v1/health/pipeline`."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import BaseSchema

#: The three states every stage and the overall roll-up can be in.
StageStatus = Literal["healthy", "degraded", "down"]


class ScannerHealth(BaseSchema):
    status: StageStatus
    last_discovery: datetime | None
    minutes_since_last_token: float | None
    #: Consecutive failed reconnects, as published by the scanner process.
    #: `None` when the scanner has published no state — it is not running, or
    #: its state key has expired.
    reconnect_attempts: int | None = None
    #: Why the scanner considers itself unhealthy, verbatim from its last
    #: connection error. `None` while connected.
    failure_reason: str | None = None


class EnrichmentHealth(BaseSchema):
    status: StageStatus
    last_snapshot: datetime | None
    minutes_since_last_snapshot: float | None
    #: Tokens whose next refresh is already due — the enrichment backlog.
    queue_depth: int
    #: Tokens that failed often enough to be parked. Not counted in the queue.
    dead_lettered: int

    # --- Sprint 28: the lane, and what it is actually delivering -------------
    # `queue_depth` above says how much work is waiting. None of it said
    # anything about the tokens the product is *displaying*, which is why this
    # endpoint reported "healthy" while 43% of Radar tokens were over an hour
    # stale and three of the visible Top 10 carried three-hour-old prices.

    #: Tokens in the priority lane, and how many of those are already due.
    priority_queue_depth: int = 0
    priority_tokens: int = 0
    #: The fresh-token nursery: current members, and how many are already due.
    #: Reported separately from the display lane above — one answers "is what
    #: the user sees fresh", the other "are new launches being observed at all".
    nursery_tokens: int = 0
    nursery_queue_depth: int = 0
    #: How long the oldest waiting item in each lane has been due, in seconds.
    #: `None` when that lane has nothing overdue.
    oldest_priority_wait_seconds: float | None = None
    oldest_normal_wait_seconds: float | None = None
    #: Observed refresh gap for tracked tokens — what the lane is *delivering*,
    #: as opposed to what it was configured to promise.
    tracked_freshness_p50_seconds: float | None = None
    tracked_freshness_p95_seconds: float | None = None
    tracked_freshness_worst_seconds: float | None = None
    #: Tracked tokens whose newest snapshot is older than the stale threshold.
    #: This is the number that should have been degrading `status` all along.
    tracked_stale_count: int = 0


class ScoringHealth(BaseSchema):
    status: StageStatus
    last_score: datetime | None
    minutes_since_last_score: float | None
    #: Tokens that have market observations but no score row yet.
    pending: int


class RadarHealth(BaseSchema):
    status: StageStatus
    last_cycle: datetime | None
    minutes_since_last_cycle: float | None
    tracked_tokens: int


class PaperMarketHealth(BaseSchema):
    """Whether the paper wallet may commit new capital, and the evidence.

    Its own block rather than fields on `EnrichmentHealth`, because it answers
    a different question. Enrichment health asks "is the pipeline working";
    this asks "is the evidence good enough to spend money on", and the second
    is strictly stricter than the first — a feed can be healthy while the open
    book is not yet re-primed.
    """

    #: HEALTHY · DEGRADED · STALE · RECOVERING.
    market_data: str
    #: ENABLED · BLOCKED.
    entry_safety: str
    #: Always ACTIVE. Stated as a field rather than assumed, because the whole
    #: design claim is that exits never depend on feed health, and a claim
    #: nobody can read on the endpoint is one nobody can check.
    exit_management: str
    #: COMPLETE · INCOMPLETE.
    recovery: str
    block_reasons: list[str] = Field(default_factory=list)
    detail: str = ""
    global_last_priced_snapshot_age: float | None = None
    recent_priced_snapshots: int = 0
    recent_priced_mints: int = 0
    open_positions_total: int = 0
    open_positions_fresh: int = 0
    open_positions_warning: int = 0
    open_positions_stale: int = 0
    #: Open positions with no priceable market. Counted separately because
    #: they cannot be recovered and so must not hold the entry gate shut —
    #: and listed, because a number excluded from a gate is exactly the one
    #: that gets forgotten.
    open_positions_unpriceable: int = 0
    oldest_open_position_snapshot_age: float | None = None
    open_position_refresh_p50: float | None = None
    open_position_refresh_p95: float | None = None
    stale_positions: list[str] = Field(default_factory=list)
    unpriceable_positions: list[str] = Field(default_factory=list)
    #: Open positions in **retired** generations, and how many of those have no
    #: recent price. Reported and deliberately not gated on: their generations
    #: are archived and nothing will re-price them, so waiting on them would be
    #: waiting for something that cannot happen. Surfaced so that scoping the
    #: gate to the live wallet does not also make 96 frozen positions invisible.
    archived_open_positions: int = 0
    archived_open_unpriced: int = 0


class PipelineHealth(BaseSchema):
    scanner: ScannerHealth
    market_enrichment: EnrichmentHealth
    scoring: ScoringHealth
    radar: RadarHealth
    #: `None` only when the paper wallet is switched off entirely.
    paper_market: PaperMarketHealth | None = None
    #: The worst status of any *enabled* stage. A stage whose feature flag is
    #: off is reported on its own but excluded here, so a deployment that
    #: deliberately runs without the scanner is not permanently degraded.
    overall: StageStatus
    environment: str
    version: str
    observed_at: datetime
