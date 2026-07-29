"""Scoring API contracts.

Two conventions carried over from the market schemas, both deliberate:

  * **Decimals serialise as strings.** A JSON float would silently round exactly
    the numbers the score's waterfall has to reconcile, and clients comparing a
    displayed contribution against a displayed total would see it fail to add up.
  * **Absence is a state, not an error.** An unscored token returns 200 with a
    null body and a `status` explaining why, mirroring `TokenMarketRead.market`.

`confidence` and `freshness` appear here but exist in no table. They are derived
per request from stored evidence and the age of the underlying snapshot, because
a stored freshness is wrong the moment it is written.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from app.models.score import ScoreGrade
from app.schemas.common import BaseSchema

#: Why a score is absent. `scored` is the only state with a body.
ScoreStatus = Literal[
    "scored",
    # Discovered, but no provider has indexed a pool yet.
    "awaiting_market",
    # Market data exists but nothing has evaluated it yet.
    "not_scored",
    # Evaluated, but too little of the model could be applied to say anything.
    "insufficient_data",
    # The engine is switched off in this environment.
    "scoring_disabled",
]

ScoreSortField = Literal[
    "score",
    "evidence",
    "market_risk",
    "opportunity_raw",
    "evaluated_at",
]
SortOrder = Literal["asc", "desc"]


class ScoreReasonRead(BaseSchema):
    """One machine-readable reason plus the sentence it renders as.

    The engine emits only codes; the template lives beside them and is applied
    here. That keeps explanations translatable and diffable, and keeps prose out
    of a path that runs tens of thousands of times an hour.
    """

    code: str = Field(description="Stable identifier, safe to branch on.")
    severity: Literal["info", "positive", "caution", "critical"]
    agent: str = Field(description="Which AI division owns this readout.")
    message: str = Field(description="Human-readable rendering of the code.")


class ScoreComponentRead(BaseSchema):
    """One line of the score's waterfall.

    Available contributions sum exactly to `opportunity_raw`; unavailable
    components contribute nothing but keep their declared weight, which is what
    makes a missing signal visible rather than quietly absent.
    """

    id: str
    agent: str
    available: bool
    score: Decimal | None = Field(default=None, description="0-100, null when unavailable.")
    declared_weight: Decimal
    effective_weight: Decimal = Field(description="After renormalisation; 0 when unavailable.")
    contribution: Decimal = Field(description="Points of the final score.")
    raw: dict[str, str | None] = Field(
        default_factory=dict, description="The measurements behind the sub-score."
    )
    reasons: list[str] = Field(default_factory=list)


class EvidenceSummary(BaseSchema):
    """How much of the picture we have, and how recently we looked.

    `evidence` is stored and time-invariant. `freshness` and `confidence` are
    computed per request, so a stalled token reads as stale without anything
    having to rewrite its row.
    """

    evidence: Decimal = Field(description="0-100. Coverage times observation depth.")
    coverage: Decimal = Field(
        description="0-100. Share of model weight that could be applied."
    )
    observations: int = Field(description="Snapshots inside the feature window.")
    freshness: Decimal = Field(description="0-1. Computed at read time.")
    confidence: Decimal = Field(description="0-100. Evidence discounted by freshness.")


class RiskSummary(BaseSchema):
    """What the risk gate took off, and whether it vetoed outright."""

    market_risk: Decimal = Field(description="0-100. Higher is more dangerous.")
    has_veto: bool = Field(description="True when the score was capped regardless of signals.")
    deduction: Decimal = Field(
        description="Points removed from the opportunity score by the risk gate."
    )


class TokenSummary(BaseSchema):
    """Just enough token identity to render a row without a second request."""

    mint_address: str
    name: str | None = None
    symbol: str | None = None


class TokenScoreRead(BaseSchema):
    """A token's current score."""

    mint_address: str
    score: Decimal = Field(description="0-100, after the risk gate.")
    opportunity_raw: Decimal = Field(description="0-100, before the risk gate.")
    grade: ScoreGrade
    is_elite: bool
    evidence: EvidenceSummary
    risk: RiskSummary
    model_version: str
    evaluated_at: datetime
    latest_snapshot_at: datetime | None = None
    previous_score: Decimal | None = Field(
        default=None, description="From the preceding history row, when one exists."
    )
    last_trigger: str | None = Field(
        default=None, description="Why the most recent history row was written."
    )
    components: list[ScoreComponentRead] = Field(default_factory=list)
    reasons: list[ScoreReasonRead] = Field(default_factory=list)


class TokenScoreEnvelope(BaseSchema):
    """The per-token response. `score` is null unless `status` is `scored`."""

    mint_address: str
    status: ScoreStatus
    score: TokenScoreRead | None = None


class ScoreHistoryEntry(BaseSchema):
    """One recorded score change.

    History is written on material change plus a periodic heartbeat, so this is
    a record of events rather than a sample of every evaluation.
    """

    evaluated_at: datetime
    score: Decimal
    delta: Decimal | None = Field(
        default=None, description="Change against the previous entry."
    )
    trigger: str = Field(description="What earned this entry a row.")
    grade: ScoreGrade
    is_elite: bool
    has_veto: bool
    evidence: Decimal
    coverage: Decimal
    market_risk: Decimal
    opportunity_raw: Decimal
    observations: int
    model_version: str
    reasons: list[ScoreReasonRead] = Field(default_factory=list)


class ScoreHistoryPage(BaseSchema):
    mint_address: str
    items: list[ScoreHistoryEntry]
    total: int
    page: int
    page_size: int
    pages: int


class TopScoreEntry(BaseSchema):
    token: TokenSummary
    score: TokenScoreRead


class AppliedFilters(BaseSchema):
    """Echo of what was actually applied.

    Defaults that silently exclude rows are how a ranking endpoint returns 200
    and an empty page with no explanation. Echoing them, alongside both counts,
    makes the exclusion visible.
    """

    min_score: Decimal | None = None
    min_confidence: Decimal | None = None
    max_risk: Decimal | None = None
    grade: ScoreGrade | None = None
    trigger: str | None = None
    model_version: str | None = None
    elite_only: bool = False
    sort: ScoreSortField = "score"
    order: SortOrder = "desc"


class TopScorePage(BaseSchema):
    items: list[TopScoreEntry]
    total: int = Field(description="Rows matching the filters.")
    candidate_total: int = Field(description="Rows before filtering, for context.")
    page: int
    page_size: int
    pages: int
    applied_filters: AppliedFilters


class ModelComponentRead(BaseSchema):
    """One declared component of the active model."""

    id: str
    agent: str
    weight: Decimal = Field(description="Declared share of the target vector.")
    available: bool = Field(
        description="False for signals whose data source does not exist yet."
    )


class GradeBandRead(BaseSchema):
    grade: ScoreGrade
    lower_bound: Decimal
    upper_bound: Decimal | None = Field(default=None, description="Null for the top band.")


class EliteGateRead(BaseSchema):
    min_score: Decimal
    min_evidence: Decimal
    max_risk_penalty: Decimal
    min_liquidity_usd: Decimal
    sustain_evaluations: int
    reachable: bool = Field(
        description=(
            "False when the model's available coverage cannot reach `min_evidence`. "
            "In v1 this is expected: the contract and holder signals do not exist yet."
        )
    )


class ModelMetadataRead(BaseSchema):
    """The active scoring model, exposed so its weights are inspectable.

    The weights are priors, not fitted parameters. Publishing them is what makes
    that claim checkable rather than asserted.
    """

    version: str
    risk_lambda: Decimal
    veto_ceiling: Decimal
    max_single_contribution: Decimal
    min_scorable_weight: Decimal
    declared_weight_total: Decimal
    available_weight_total: Decimal = Field(
        description="Ceiling on coverage, and therefore on evidence, for this model."
    )
    components: list[ModelComponentRead]
    grade_bands: list[GradeBandRead]
    elite_gate: EliteGateRead
    scoring_enabled: bool
