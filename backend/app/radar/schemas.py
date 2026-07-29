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
    peak_at: datetime | None
    days_since_detection: Decimal

    is_active: bool
    detection_reason: list[str]
    model_version: str
    last_evaluated_at: datetime


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
