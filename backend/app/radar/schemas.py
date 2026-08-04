"""Radar API contracts.

Decimals serialise as **strings**, matching the scoring API. A JSON float would
round exactly the multiples the track record is judged on — and a track record
whose arithmetic does not reconcile on screen is worse than none.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import Field

from app.schemas.common import BaseSchema
from app.schemas.market_strip import MarketStripOut


class DimensionOut(BaseSchema):
    """One axis of the opportunity score."""

    id: str
    label: str
    available: bool
    score: Decimal | None
    #: Share of the final score this axis carried, after renormalisation.
    effective_weight: Decimal | None
    reasons: list[str]


class ReasonOut(BaseSchema):
    code: str
    agent: str
    severity: str
    message: str


class AchievementOut(BaseSchema):
    tier: str
    multiple: Decimal
    achieved_at: datetime
    price_at_achievement: Decimal | None
    market_cap_at_achievement: Decimal | None
    days_to_achieve: Decimal | None


class BaseRateOut(BaseSchema):
    """What happened to past detections of this kind.

    Measured history, never a forecast. A rate here says "of the N tokens the
    Radar previously called this, X reached 2x" — it makes no claim about the
    token in front of you, and the wording on every surface must keep that
    distinction.

    `sufficient` is false when the sample is too small to quote. The counts are
    still returned so a reader can see exactly how thin it is, but the page must
    print `insufficient_reason` instead of a percentage: a rate from n=1 is
    noise wearing the costume of evidence.
    """

    category: str
    sample: int
    reached_2x: int
    reached_5x: int
    reached_10x: int
    reached_100x: int
    median_peak_multiple: Decimal | None = None
    median_current_multiple: Decimal | None = None
    sufficient: bool = False
    insufficient_reason: str | None = None
    #: Published so the bar is checkable rather than asserted.
    minimum_sample: int = 0


class RadarSignalOut(BaseSchema):
    """The live signal beside a Radar row, if the engine has one.

    A deliberate subset of the board's `SignalOut`: the Radar answers "should I
    care, and why now?" in one line, and the full evidence list belongs on the
    token page. Every string here is rendered by the backend from stable reason
    codes — the client never composes prose about a token.
    """

    signal_type: str
    provider: str
    severity: str
    #: The engine's own headline for the transition. Displayed verbatim.
    headline: str
    #: One sentence on what changed. This is the "why now" column.
    why_now: str
    #: What the engine derived from the provider's claim, 0-100.
    confidence: Decimal
    #: Seconds until the claim lapses. A signal is a statement with a shelf
    #: life, and a row that does not show it invites acting on a stale one.
    expires_in_seconds: int


class RadarEntryOut(BaseSchema):
    """A Radar opportunity, with everything measured from first detection."""

    mint_address: str
    name: str | None = None
    symbol: str | None = None

    category: str
    #: The category assigned at first detection. Kept beside the current one so
    #: a re-classification is visible rather than silently rewriting history.
    original_category: str
    opportunity_score: Decimal
    confidence: Decimal

    first_detected_at: datetime
    first_price: Decimal | None
    first_market_cap: Decimal | None
    first_liquidity: Decimal | None
    first_opportunity_score: Decimal

    current_price: Decimal | None
    current_market_cap: Decimal | None
    current_liquidity: Decimal | None

    #: Multiples from detection: 1.0 is unchanged, 2.0 is a double.
    current_multiple: Decimal | None
    peak_multiple: Decimal | None
    peak_price: Decimal | None
    #: The highest market cap this entry ever reached. Stored on the row since
    #: detection; surfaced because the record shows detection/current/peak
    #: together and a multiple alone hides the scale it moved at.
    peak_market_cap: Decimal | None
    peak_at: datetime | None
    days_since_detection: Decimal

    is_active: bool
    detection_reason: list[str]
    model_version: str
    last_evaluated_at: datetime
    #: Tiers this entry has ever reached, from `radar_achievements`. Read from
    #: the achievement rows rather than recomputed from `peak_multiple` so the
    #: badge and the tier counts can never disagree — and so a badge, once
    #: earned, survives a later correction to the peak.
    achieved_tiers: list[str] = Field(default_factory=list)
    #: `alive` | `unknown`. Never `inactive` — see `observed_within`.
    liveness: str = "unknown"
    #: How past detections in this same category actually performed. A property
    #: of the category, not a prediction about this token.
    base_rate: BaseRateOut | None = None

    # --- Sprint 23: what a trader needs before acting on a row ---------------

    #: Price, size and flow as last observed. `None` when the token has never
    #: been priced — never a zeroed strip.
    market: MarketStripOut | None = None
    #: Seconds since the mint existed on chain, falling back to when we first
    #: saw it. `None` when neither is known.
    age_seconds: int | None = None
    #: The risk dimension from the newest recorded snapshot, 0-100, where a
    #: **low** score is the dangerous one — it is scored like every other
    #: dimension, so "good" is high throughout. `None` when the sweep could not
    #: assess risk, which is charged to `evidence` rather than hidden.
    risk_score: Decimal | None = None
    #: The reason codes behind that risk score, verbatim from the snapshot.
    risk_reasons: list[str] = Field(default_factory=list)
    #: Share of the model's declared weight that had data when this row was
    #: last scored, 0-100. This is the honesty number: a 90 scored on a third
    #: of the model is not the same claim as a 90 scored on all of it.
    evidence: Decimal | None = None
    #: The live Opportunity Engine signal for this token, when one exists. The
    #: Radar ranks; the signal says what changed and when the claim expires.
    #: `None` means nothing is live — never that nothing ever happened.
    signal: RadarSignalOut | None = None


class RadarDetailOut(RadarEntryOut):
    """One opportunity in full, including why."""

    dimensions: list[DimensionOut]
    reasons: list[ReasonOut]
    achievements: list[AchievementOut]


class RadarPage(BaseSchema):
    items: list[RadarEntryOut]
    total: int
    page: int
    page_size: int
    applied_filters: dict[str, object]


class RadarDiscoveredCandidateOut(BaseSchema):
    """A Pump.fun admission candidate, before any intelligence scoring."""

    token: str
    name: str | None = None
    symbol: str | None = None
    creation_time: datetime
    age_days: Decimal
    market_cap: Decimal | None
    liquidity: Decimal | None
    volume: Decimal | None
    holder_count: int | None = None
    last_scan_time: datetime


class RadarDiscoveredPage(BaseSchema):
    items: list[RadarDiscoveredCandidateOut]
    total: int
    page: int
    page_size: int


class RadarSnapshotOut(BaseSchema):
    captured_at: datetime
    price: Decimal | None
    market_cap: Decimal | None
    liquidity: Decimal | None
    opportunity_score: Decimal
    confidence: Decimal
    coverage: Decimal
    category: str
    reasons: list[str]


class RadarHistoryOut(BaseSchema):
    mint_address: str
    items: list[RadarSnapshotOut]
    total: int


class TierCount(BaseSchema):
    tier: str
    count: int


class PerformanceOut(BaseSchema):
    """The platform's track record.

    Deliberately reports losers alongside winners. A success rate computed only
    over the entries that worked is not a success rate.
    """

    total_opportunities: int
    active_opportunities: int
    average_peak_multiple: Decimal | None
    median_current_multiple: Decimal | None
    best_peak_multiple: Decimal | None
    worst_current_multiple: Decimal | None
    tiers: list[TierCount]
    #: Share that reached at least 2x, as a fraction of everything ever detected.
    success_rate: Decimal | None

    # --- Track record --------------------------------------------------------
    # Measured aggregates over the permanent record. `None` where no row
    # supports the figure — rendered as "—", never as zero.
    expired_opportunities: int = 0
    median_peak_multiple: Decimal | None = None
    average_drawdown: Decimal | None = None
    average_days_to_2x: Decimal | None = None
    average_days_tracked: Decimal | None = None
    average_detection_market_cap: Decimal | None = None
    average_peak_market_cap: Decimal | None = None
    largest_peak_market_cap: Decimal | None = None
    average_current_multiple: Decimal | None = None
    average_days_to_5x: Decimal | None = None
    above_entry: int = 0
    below_entry: int = 0
    #: Liveness, measured only. `alive` means a market was observed recently;
    #: `unknown` means it was not, which is not the same as dead. `inactive` is
    #: never reported because nothing in the record establishes death.
    alive: int = 0
    unknown: int = 0
    inactive: int = 0
    last_detection_at: datetime | None = None
    #: When this reading was taken, so a stale page is visibly stale.
    observed_at: datetime | None = None


class TimelineEventOut(BaseSchema):
    """One entry in the Radar's own history.

    Projected from stored rows — a detection or a tier crossing — never written
    for the feed itself, so it can never disagree with the record.
    """

    kind: str
    mint_address: str
    name: str | None = None
    symbol: str | None = None
    occurred_at: datetime
    tier: str | None = None
    market_cap: Decimal | None = None
    value: Decimal | None = None


class BenchmarkOut(BaseSchema):
    """What buying every detection equally would have returned.

    The only benchmark the stored history can answer. Holding SOL is absent
    because no SOL price series is recorded, and `sol_note` says so rather than
    leaving the reader to assume it was omitted by accident.
    """

    entries: int
    average_current_multiple: Decimal | None = None
    average_peak_multiple: Decimal | None = None
    median_current_multiple: Decimal | None = None
    above_entry: int = 0
    below_entry: int = 0
    sol_note: str
    paper_wallet_note: str


class CategoryOut(BaseSchema):
    id: str
    label: str
    description: str
    #: False when the current model can never award it — see `community.py`.
    reachable: bool
    reachable_note: str | None = None


class ModelOut(BaseSchema):
    """The published Radar model, so its claims are checkable."""

    version: str
    dimensions: list[dict[str, object]] = Field(default_factory=list)
    declared_weight_total: Decimal
    available_weight_total: Decimal
    min_radar_score: Decimal
    min_radar_confidence: Decimal
    min_risk_floor: Decimal
    categories: list[CategoryOut]
    achievement_tiers: list[str]
