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

    A deliberate subset of the board's `SignalOut`, narrowed again in Sprint 24:
    `provider`, `severity`, `strength`, `confirmations` and the engine's own
    `confidence` are gone from this surface. They are accurate and they are
    internal — a reader who sees `provider: breakout` learns nothing they can
    act on, and a reader who sees `confidence: 61.53` will read it as a
    probability, which it is not.

    What remains is a stable code to key on and one label to display.
    """

    #: A stable identifier, not prose. Clients may branch on it; they must not
    #: print it — an unlabelled type renders nothing rather than its raw code.
    signal_type: str
    #: The signal in trader language, rendered by the backend from
    #: `readout.SIGNAL_LABEL`. Displayed verbatim.
    label: str
    #: Seconds until the claim lapses. A signal is a statement with a shelf
    #: life, and a row that does not show it invites acting on a stale one.
    expires_in_seconds: int


class WhyNowOut(BaseSchema):
    """One sentence on why this row is interesting now.

    Present on **every** entry, not only the ones carrying a live signal —
    measured on the live board, nine of the top ten had no signal, so a
    why-now derived from signals alone left nine rows silent.

    Rendered server-side from stored facts, like every other explanation in
    this codebase. `code` is what a client keys on; `sentence` is what it
    displays. The client never composes either.
    """

    code: str
    sentence: str


class RadarEntryOut(BaseSchema):
    """A Radar opportunity, with everything measured from first detection."""

    mint_address: str
    name: str | None = None
    symbol: str | None = None
    image_url: str | None = None

    category: str
    #: The category assigned at first detection. Kept beside the current one so
    #: a re-classification is visible rather than silently rewriting history.
    original_category: str
    opportunity_score: Decimal
    confidence: Decimal

    #: When MEMESCOPE first *discovered* the mint — the minimum across every
    #: stored discovery record for it. Distinct from `first_detected_at`, which
    #: is admission to the Radar and happens later. `None` only when no
    #: discovery row survives for the mint; clients render that as unavailable
    #: rather than substituting a nearby timestamp.
    discovered_at: datetime | None = None

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
    #: `low` | `medium` | `high` | `extreme`, cut from `risk_score` against the
    #: thresholds published in `readout.RISK_BANDS`. `None` when risk was not
    #: assessed — that is an absence, not a fifth band, and must not render as
    #: one. Banded on the server so the cuts are auditable beside the number
    #: that produced them rather than invented in a component.
    risk_band: str | None = None
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
    #: Why this row is interesting now, in one sentence. Always present: the
    #: fallback describes the detection itself, which is always true.
    why_now: WhyNowOut | None = None


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


class FreshDetectedTokenOut(BaseSchema):
    """A newly discovered token joined to whatever enrichment exists so far."""

    mint_address: str
    name: str | None = None
    symbol: str | None = None
    image_url: str | None = None
    discovered_at: datetime
    block_time: datetime | None = None
    metadata_status: str
    current_market_cap: Decimal | None = None
    current_liquidity: Decimal | None = None
    current_price: Decimal | None = None
    market_observed_at: datetime | None = None
    radar_score: Decimal | None = None
    radar_category: str | None = None
    radar_status: str | None = None


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


class ExecutableStatsOut(BaseSchema):
    """Derived EXECUTABLE truth beside the raw record — never instead of it.

    Raw figures above value provider prints; these value what a $10 position
    could actually have sold for (fees + calibrated impact paid, ingest-flagged
    prints excluded, horizons stated). Absent until the compute has coverage.
    """

    method_version: str
    #: Admissions whose 24h horizon has fully elapsed inside stored data.
    decided: int
    #: Of `decided`: share whose sellable value ever reached 2x within 24h.
    reached_2x_24h_rate: Decimal | None
    reached_125_24h_rate: Decimal | None
    #: Median sellable value per $1 at the 24h mark, over `decided`.
    median_final_value_frac_24h: Decimal | None
    #: decided / total admissions — how much of the record is computed yet.
    coverage: Decimal | None


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
    #: RAW MARKET PRINT vs EXECUTABLE OUTCOME, distinguished by name (V4 P2).
    executable: ExecutableStatsOut | None = None
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
    image_url: str | None = None
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
