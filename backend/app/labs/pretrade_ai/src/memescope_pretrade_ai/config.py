from __future__ import annotations
from hashlib import sha256
from pathlib import Path
from typing import Literal
import json
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

class ThresholdConfig(StrictModel):
    accept_score: float = Field(72.0, ge=0, le=100)
    review_score: float = Field(55.0, ge=0, le=100)
    hard_reject_risk: float = Field(80.0, ge=0, le=100)
    minimum_feature_completeness: float = Field(0.65, ge=0, le=1)
    @model_validator(mode="after")
    def ordered(self):
        if self.accept_score <= self.review_score:
            raise ValueError("accept_score must be greater than review_score")
        return self

class HardGateConfig(StrictModel):
    minimum_liquidity_usd: float = 50_000
    maximum_pool_lifetime_swaps: int = 99
    maximum_quote_age_seconds: float = 5.0
    maximum_buy_price_impact_pct: float = 1.0
    maximum_round_trip_loss_pct: float = 2.0
    require_safe_mint_authority: bool = True
    require_safe_freeze_authority: bool = True
    confirmed_rug_link_min_identity_confidence: float = 0.70

class RiskWeights(StrictModel):
    creator_confirmed_rug: float = 42.0
    funder_confirmed_rug: float = 32.0
    recent_link: float = 18.0
    creator_sale: float = 18.0
    reserve_decline: float = 12.0
    missing_identity: float = 8.0
    creator_sale_reference_pct: float = 0.25
    reserve_decline_reference_pct: float = 10.0

class ScoringConfig(StrictModel):
    model_weight: float = Field(0.75, ge=0, le=1)
    liquidity_prior_weight: float = Field(0.25, ge=0, le=1)
    risk_penalty_weight: float = Field(0.45, ge=0, le=1)
    preferred_liquidity_low_usd: float = 50_000
    preferred_liquidity_high_usd: float = 75_000
    excluded_research_band_low_usd: float = 150_000
    excluded_research_band_high_usd: float = 200_000
    required_features: list[str] = [
        "liquidity_usd", "pool_lifetime_swaps", "quote_age_seconds",
        "buy_price_impact_pct", "immediate_round_trip_loss_pct",
        "sell_route_available", "mint_authority_safe", "freeze_authority_safe",
    ]
    thresholds: ThresholdConfig = ThresholdConfig()
    hard_gates: HardGateConfig = HardGateConfig()
    risk_weights: RiskWeights = RiskWeights()
    @model_validator(mode="after")
    def weights(self):
        if self.model_weight + self.liquidity_prior_weight <= 0:
            raise ValueError("model_weight + liquidity_prior_weight must be positive")
        return self

class SplitConfig(StrictModel):
    train_fraction: float = Field(0.60, gt=0, lt=1)
    validation_fraction: float = Field(0.20, gt=0, lt=1)
    test_fraction: float = Field(0.20, gt=0, lt=1)
    embargo_minutes: int = Field(15, ge=0)
    purge_group_fields: list[Literal["mint", "pool", "creator_cluster_id", "funder_cluster_id"]] = ["mint", "creator_cluster_id", "funder_cluster_id"]
    @model_validator(mode="after")
    def total(self):
        if abs(self.train_fraction + self.validation_fraction + self.test_fraction - 1.0) > 1e-9:
            raise ValueError("split fractions must total 1")
        return self

class TrainingConfig(StrictModel):
    target: Literal["positive_matched_size_net_pnl"] = "positive_matched_size_net_pnl"
    minimum_rows: int = Field(30, ge=12)
    random_state: int = 42
    class_weight: Literal["balanced", "none"] = "balanced"
    max_iter: int = 1000
    split: SplitConfig = SplitConfig()

class BacktestConfig(StrictModel):
    starting_cash_usd: float = 300.0
    expected_all_in_entry_cost_usd: float = 10.0
    entry_cost_tolerance_usd: float = 0.01
    maximum_open_positions: int = 6
    maximum_gross_cost_exposure_usd: float = 60.0
    maximum_equity_exposure_fraction: float = 0.20
    accept_decisions: list[str] = ["ACCEPT"]

class IntegrationConfig(StrictModel):
    output_mode: Literal["local_jsonl_only"] = "local_jsonl_only"
    execution_authorized: Literal[False] = False
    production_writes_authorized: Literal[False] = False
    require_acknowledgement_flag: bool = True

class AppConfig(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    scoring: ScoringConfig = ScoringConfig()
    training: TrainingConfig = TrainingConfig()
    backtest: BacktestConfig = BacktestConfig()
    integration: IntegrationConfig = IntegrationConfig()

def load_config(path: str | Path) -> AppConfig:
    with Path(path).open("r", encoding="utf-8") as f:
        return AppConfig.model_validate(yaml.safe_load(f))

def config_hash(config: AppConfig) -> str:
    payload = json.dumps(config.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode()).hexdigest()
