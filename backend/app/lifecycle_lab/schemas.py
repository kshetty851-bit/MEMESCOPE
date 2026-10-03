"""Response and request models for `/api/v1/lifecycle-lab`.

They mirror docs/MEME_LIFECYCLE_LAB.md, "API response contract", field for
field — the frontend codes against that section. Money, prices and ratios are
strings (Decimal) or null; ratios are FRACTIONS (0.05 = 5%). A value that could
not be measured is a ``Measured`` with a reason, never 0.

Request bodies forbid unknown fields: a manual link that arrives with its own
``linked_at`` is refused (422), not silently re-dated.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from app.lifecycle_lab.domain import AliasKind
from app.schemas.common import BaseSchema

#: Solana mints are base58, 32 to 44 characters.
MINT_PATTERN = r"^[1-9A-HJ-NP-Za-km-z]{32,44}$"
SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{0,63}$"
#: First path segments of the Lab's own routes (API and the frontend's static
#: pages). A meme slug equal to one would be shadowed by the static route.
RESERVED_SLUGS = frozenset(
    {"quality", "research-status", "health", "overview", "experiments", "runs", "memes"}
)


class Measured(BaseSchema):
    value: str | None
    unavailable_reason: str | None


class SourceHealth(BaseSchema):
    source: str
    label: str
    status: str
    reason: str | None
    last_run_at: datetime | None
    data_class: str
    observations_24h: int | None


class PortfolioOut(BaseSchema):
    run_id: str | None
    as_of: datetime | None
    starting_capital: str
    equity: str | None
    cash: str | None
    deployed: str | None
    realized_pnl: str | None
    unrealized_pnl: str | None
    #: Fraction of starting capital.
    roi: str | None
    #: Maximum drawdown, as a fraction below the running peak.
    drawdown: str | None
    trades: int
    open_positions: int
    sample_label: str
    unavailable_reason: str | None


class ExperimentSummary(BaseSchema):
    experiment_key: str
    split_meaningful: bool
    split_note: str | None
    train: list[datetime | None]
    validation: list[datetime | None]
    test: list[datetime | None]


class ResearchRequirement(BaseSchema):
    key: str
    label: str
    threshold: str
    #: null = could not be measured; then ``met`` is false and ``reason`` says why.
    observed: str | None
    met: bool
    reason: str | None


class ResearchStatusOut(BaseSchema):
    state: str
    #: "UNCERTAIN" in every state this phase can reach (no verdict engine).
    verdict: str
    verdict_engine_available: bool
    forward_start: datetime | None
    forward_days: float | None
    experiment_key: str | None
    requirements: list[ResearchRequirement]
    explanation: str


class Overview(BaseSchema):
    lab_enabled: bool
    real_trading: bool
    mode: str
    forward_start: datetime | None
    forward_days: float | None
    portfolio: PortfolioOut
    experiment: ExperimentSummary | None
    sources: list[SourceHealth]
    tracked_memes: int
    linked_tokens: int
    notes: list[str]
    research_status: ResearchStatusOut


class HealthOut(BaseSchema):
    generated_at: datetime
    sources: list[SourceHealth]


class TokenRef(BaseSchema):
    mint: str
    symbol: str | None
    name: str | None
    link_method: str
    confidence: str
    linked_at: datetime


class RadarAttention(BaseSchema):
    mentions_1h: Measured
    mentions_24h: Measured
    velocity: Measured
    acceleration: Measured
    baseline_multiple: Measured
    platform_count: Measured


class MemeRow(BaseSchema):
    slug: str
    display_name: str
    tokens: list[TokenRef]
    primary_mint: str | None
    token_age_seconds: int | None
    age_bucket: str
    market_cap: str | None
    liquidity_usd: str | None
    volume_1h: str | None
    #: Fraction (0.05 = +5%).
    price_change_1h: str | None
    attention: RadarAttention
    lifecycle_state: str
    #: volume_growth: 1h volume over the preceding hour, as a ratio.
    market_activity: Measured
    data_freshness_seconds: int | None
    paper_status: str
    contains_backfill: bool


class MemesOut(BaseSchema):
    generated_at: datetime
    items: list[MemeRow]


class MemeIdentity(BaseSchema):
    slug: str
    display_name: str
    description: str | None
    tracking_started_at: datetime
    wikipedia_title: str | None
    gdelt_query: str | None


class AliasOut(BaseSchema):
    alias: str
    kind: str
    added_at: datetime


class LinkOut(BaseSchema):
    mint: str
    method: str
    confidence: str
    linked_at: datetime
    unlinked_at: datetime | None


class SeriesPoint(BaseSchema):
    t: datetime
    #: null = nobody observed that hour; never 0 for absence.
    value: str | None


class Series(BaseSchema):
    attention: list[SeriesPoint]
    price: list[SeriesPoint]
    volume: list[SeriesPoint]
    per_source: dict[str, list[SeriesPoint]]
    #: Points before this instant may contain exploratory backfill.
    backfill_before: datetime | None


class Marker(BaseSchema):
    t: datetime
    kind: str
    label: str
    event_type: str | None
    mint: str | None


class EventOut(BaseSchema):
    event_type: str
    label: str
    detected_at: datetime
    mint: str | None
    divergence_case: str | None
    lifecycle_state: str | None
    mode: str
    contains_backfill: bool
    #: Horizon ("5m" … "24h") → fractional return after detection.
    returns: dict[str, Measured]
    price_at_detection: str | None
    run_up_before_detection: Measured


class TimelineItem(BaseSchema):
    at: str | None
    kind: str
    #: Rendered prose for the stable ``kind`` code.
    detail: str


class TradeOut(BaseSchema):
    trade_key: str
    arm: str
    mint: str
    entry_at: datetime
    entry_price: str | None
    size_usd: str | None
    exit_at: datetime | None
    exit_price: str | None
    exit_reason: str | None
    exit_reason_text: str | None
    pnl_usd: str | None
    #: Fraction of the position's cost basis (0.05 = +5%).
    return_pct: str | None
    status: str
    entry_reason: str
    evidence_timeline: list[TimelineItem]
    contains_backfill: bool


class MemeDetail(BaseSchema):
    meme: MemeIdentity
    aliases: list[AliasOut]
    links: list[LinkOut]
    series: Series
    markers: list[Marker]
    events: list[EventOut]
    trades: list[TradeOut]
    data_label: str
    contains_backfill: bool
    sources: list[SourceHealth]


class ExperimentOut(BaseSchema):
    experiment_key: str
    hypothesis: str
    arm: str
    mode: str
    spec_hash: str
    created_at: datetime
    data_cutoff: datetime | None
    train: list[datetime | None]
    validation: list[datetime | None]
    test: list[datetime | None]
    split_meaningful: bool
    split_note: str | None
    status: str


class ExperimentsOut(BaseSchema):
    items: list[ExperimentOut]


class RunOut(BaseSchema):
    id: str
    experiment_id: str
    arm: str | None
    mode: str
    segment: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    window_start: datetime
    window_end: datetime
    input_fingerprint: str | None
    trades_count: int
    ending_equity: str | None
    contains_backfill: bool
    hindsight_links: bool
    error: str | None
    duration_seconds: float | None
    recompute: str | None


class SnapshotOut(BaseSchema):
    at: datetime
    equity: str | None
    cash: str | None
    deployed: str | None
    realized_pnl: str | None
    unrealized_pnl: str | None
    open_positions: int
    peak_equity: str | None
    drawdown: str | None


class RunDetail(BaseSchema):
    run: RunOut
    #: ``LabMetrics.to_dict()``; ratios are fractions.
    metrics: dict[str, Any]
    snapshots: list[SnapshotOut]
    trades: list[TradeOut]


# --------------------------------------------------------------------------
# Validation phase: data quality and the per-meme audit trail
# --------------------------------------------------------------------------


class ObservationSplit(BaseSchema):
    forward: int
    backfill: int


class SourceCollectionStats(BaseSchema):
    source: str
    label: str
    runs_24h: int
    available: int
    unavailable: int
    disabled: int
    error: int
    stale: int
    partial: int
    #: AVAILABLE / (runs - DISABLED); null when that denominator is zero.
    success_rate_24h: str | None
    last_success_at: datetime | None
    last_status: str | None
    last_reason: str | None


class CollectionStats(BaseSchema):
    runs_24h: int
    failures_24h: int
    success_rate_24h: str | None
    by_source: list[SourceCollectionStats]


class QualityMemeRef(BaseSchema):
    slug: str
    display_name: str


class QualityTokenRef(BaseSchema):
    mint: str
    meme_slug: str


class QualityIncompleteToken(QualityTokenRef):
    missing: list[str]


class QualityReport(BaseSchema):
    generated_at: datetime
    tracked_memes: int
    tracked_tokens: int
    observations_today: ObservationSplit
    observations_week: ObservationSplit
    collection: CollectionStats
    unavailable_sources: list[str]
    stale_sources: list[str]
    oldest_forward_observation_at: datetime | None
    newest_forward_observation_at: datetime | None
    memes_without_observations: list[QualityMemeRef]
    tokens_without_market_history: list[QualityTokenRef]
    tokens_with_incomplete_market_data: list[QualityIncompleteToken]


class AuditLink(LinkOut):
    linked_by: str | None
    evidence: Any


class AuditSource(BaseSchema):
    source: str
    label: str
    status: str
    reason: str | None
    first_observation_at: datetime | None
    latest_observation_at: datetime | None
    observation_count: int
    forward_count: int
    backfill_count: int


class AuditMarket(BaseSchema):
    mint: str
    first_observation_at: datetime | None
    latest_observation_at: datetime | None
    observation_count: int
    missing_fields: list[str]


class AuditAttention(BaseSchema):
    mentions_1h: Measured
    velocity: Measured
    acceleration: Measured
    baseline_multiple: Measured


class CollectionPriorityOut(BaseSchema):
    level: str
    #: The GDELT collection interval at this level.
    interval_seconds: int
    reason: str


class MemeQuality(BaseSchema):
    meme: MemeIdentity
    aliases: list[AliasOut]
    links: list[AuditLink]
    sources: list[AuditSource]
    market: list[AuditMarket]
    lifecycle_state: str
    attention: AuditAttention
    divergence_case: str
    collection_priority: CollectionPriorityOut


# --------------------------------------------------------------------------
# Requests (admin curation)
# --------------------------------------------------------------------------


class _Request(BaseSchema):
    model_config = ConfigDict(extra="forbid")


class AliasIn(_Request):
    alias: str = Field(min_length=1, max_length=200)
    kind: AliasKind


class MemeCreate(_Request):
    slug: str = Field(pattern=SLUG_PATTERN)
    display_name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    wikipedia_title: str | None = Field(default=None, max_length=300)
    gdelt_query: str | None = Field(default=None, max_length=500)
    aliases: list[AliasIn] = Field(default_factory=list, max_length=50)

    @field_validator("slug")
    @classmethod
    def _slug_not_reserved(cls, value: str) -> str:
        if value in RESERVED_SLUGS:
            raise ValueError(f"{value!r} is reserved for a Lab page; choose another slug.")
        return value


class MemeCreated(BaseSchema):
    slug: str
    display_name: str
    description: str | None
    tracking_started_at: datetime
    wikipedia_title: str | None
    gdelt_query: str | None
    aliases: list[AliasOut]


class AliasCreated(AliasOut):
    created: bool


class ManualLinkIn(_Request):
    """``linked_at`` is deliberately absent: the server stamps it."""

    mint: str = Field(pattern=MINT_PATTERN)
    confidence: Decimal = Field(gt=0, le=1, max_digits=5, decimal_places=4)
    #: Only methods that can rest on evidence. A ticker, symbol or alias match
    #: (exact_name / exact_symbol / alias_match) is never sufficient for a
    #: curated link, so those values fail validation (422).
    method: Literal["manual", "website_match", "social_link_match"] = "manual"
    #: Where the match can be checked. Required: a link without a source cannot
    #: be audited.
    evidence_url: str = Field(pattern=r"^https?://\S+$", max_length=2048)
    #: How identity was verified. Required for ``manual``.
    evidence_note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _manual_needs_a_note(self) -> ManualLinkIn:
        if self.method == "manual" and not (self.evidence_note or "").strip():
            raise ValueError("evidence_note is required when method is 'manual'.")
        return self


class LinkCreated(LinkOut):
    created: bool


class BackfillIn(_Request):
    start: datetime
    end: datetime


class BackfillQueued(BaseSchema):
    queued: bool
    slug: str
    start: datetime
    end: datetime
    data_class: str
