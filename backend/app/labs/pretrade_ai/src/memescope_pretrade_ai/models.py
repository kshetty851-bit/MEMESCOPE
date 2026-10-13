from __future__ import annotations
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

class ObservedValue(StrictModel):
    value: float | int | bool | str | None
    observed_at: datetime
    source: str
    quality: Literal["observed", "derived", "backfilled", "unknown"] = "observed"
    @field_validator("observed_at")
    @classmethod
    def aware(cls, v):
        if v.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        return v

class IdentitySnapshot(StrictModel):
    creator_address: str | None = None
    funder_address: str | None = None
    creator_cluster_id: str | None = None
    funder_cluster_id: str | None = None
    linkage_observed_at: datetime | None = None
    linkage_source: str | None = None
    @field_validator("linkage_observed_at")
    @classmethod
    def aware(cls, v):
        if v is not None and v.tzinfo is None:
            raise ValueError("linkage_observed_at must be timezone-aware")
        return v

class Outcome(StrictModel):
    label_available_ts: datetime
    exit_ts: datetime
    matched_size_entry_cost_usd: float = Field(gt=0)
    matched_size_exit_proceeds_usd: float = Field(ge=0)
    all_costs_included: bool
    unresolved: bool = False
    source: str
    @field_validator("label_available_ts", "exit_ts")
    @classmethod
    def aware(cls, v):
        if v.tzinfo is None:
            raise ValueError("outcome timestamps must be timezone-aware")
        return v
    @property
    def net_pnl_usd(self) -> float:
        return self.matched_size_exit_proceeds_usd - self.matched_size_entry_cost_usd

class Opportunity(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    opportunity_id: str
    mint: str
    pool: str
    decision_ts: datetime
    strategy_version: str
    universe: str
    baseline_eligible: bool = Field(strict=True)
    features: dict[str, ObservedValue]
    identity: IdentitySnapshot = Field(default_factory=IdentitySnapshot)
    outcome: Outcome | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("decision_ts")
    @classmethod
    def aware(cls, v):
        if v.tzinfo is None:
            raise ValueError("decision_ts must be timezone-aware")
        return v

    @model_validator(mode="after")
    def point_in_time(self):
        future = [name for name, obs in self.features.items() if obs.observed_at > self.decision_ts]
        if future:
            raise ValueError(f"feature observations after decision_ts: {future}")
        if self.identity.linkage_observed_at and self.identity.linkage_observed_at > self.decision_ts:
            raise ValueError("identity linkage was not knowable at decision time")
        has_identity = any((self.identity.creator_address, self.identity.funder_address,
                            self.identity.creator_cluster_id, self.identity.funder_cluster_id))
        if has_identity and (not self.identity.linkage_observed_at or not self.identity.linkage_source):
            raise ValueError("identity linkage requires an observation timestamp and source")
        if self.outcome:
            if self.outcome.exit_ts < self.decision_ts:
                raise ValueError("exit_ts precedes decision_ts")
            if self.outcome.label_available_ts < self.outcome.exit_ts:
                raise ValueError("label_available_ts precedes exit_ts")
        return self

class ScoreResult(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    opportunity_id: str
    mint: str
    pool: str
    decision_ts: datetime
    decision: Literal["ACCEPT", "REVIEW", "REJECT", "INSUFFICIENT_DATA"]
    score: float
    model_probability: float | None
    liquidity_prior: float
    creator_funder_risk_score: float
    feature_completeness: float
    reasons: list[str]
    model_version: str
    execution_authorized: Literal[False] = False
    production_write_authorized: Literal[False] = False
