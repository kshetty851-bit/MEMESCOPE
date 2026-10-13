from __future__ import annotations
import math
from .config import AppConfig
from .features import completeness, feature_frame, missing_required, numeric_feature
from .model import ModelBundle
from .models import Opportunity, ScoreResult
from .risk import creator_funder_risk

def _liquidity_prior(liquidity: float, cfg) -> float:
    if liquidity != liquidity: return 0.0
    if liquidity < cfg.hard_gates.minimum_liquidity_usd: return 0.0
    if cfg.preferred_liquidity_low_usd <= liquidity < cfg.preferred_liquidity_high_usd: return 88.0
    if cfg.preferred_liquidity_high_usd <= liquidity < 100_000: return 72.0
    if 100_000 <= liquidity < cfg.excluded_research_band_low_usd: return 52.0
    if cfg.excluded_research_band_low_usd <= liquidity < cfg.excluded_research_band_high_usd: return 28.0
    return 46.0

def _hard_gate_reasons(op: Opportunity, cfg) -> list[str]:
    g = cfg.hard_gates; reasons = []
    checks = [
        ("liquidity_usd", lambda x: x >= g.minimum_liquidity_usd, f"liquidity below {g.minimum_liquidity_usd}"),
        ("pool_lifetime_swaps", lambda x: x <= g.maximum_pool_lifetime_swaps, "pool lifetime swaps exceed configured quiet-pool gate"),
        ("quote_age_seconds", lambda x: x <= g.maximum_quote_age_seconds, "quote too old"),
        ("buy_price_impact_pct", lambda x: x <= g.maximum_buy_price_impact_pct, "buy price impact too high"),
        ("immediate_round_trip_loss_pct", lambda x: x <= g.maximum_round_trip_loss_pct, "immediate round-trip loss too high"),
        ("sell_route_available", lambda x: x >= 0.5, "sell route is unavailable"),
    ]
    for name, predicate, reason in checks:
        value = numeric_feature(op, name)
        if value == value and not predicate(value): reasons.append(reason)
    for name, enabled in [("mint_authority_safe", g.require_safe_mint_authority), ("freeze_authority_safe", g.require_safe_freeze_authority)]:
        value = numeric_feature(op, name)
        if enabled and value == value and value < 0.5: reasons.append(f"{name} failed")
    return reasons

def _rules_quality(op: Opportunity, liquidity_prior: float) -> float:
    score = liquidity_prior
    adjustments = []
    def add(name, good, bad):
        v = numeric_feature(op, name)
        if v == v: adjustments.append(good(v) if callable(good) else (good if v else bad))
    add("unique_buyers_30s", lambda v: min(8.0, v/3), 0)
    add("buy_sell_notional_ratio_30s", lambda v: min(8.0, max(-8.0, (v-1.0)*5)), 0)
    add("reserve_decline_30s_pct", lambda v: -min(12.0, v), 0)
    add("buy_price_impact_pct", lambda v: -min(8.0, v*4), 0)
    add("immediate_round_trip_loss_pct", lambda v: -min(8.0, v*3), 0)
    if adjustments: score = 0.78*score + 0.22*max(0.0, min(100.0, 50 + sum(adjustments)))
    return score

def score_opportunity(op: Opportunity, config: AppConfig, bundle: ModelBundle | None = None) -> ScoreResult:
    cfg = config.scoring
    missing = missing_required(op, cfg.required_features)
    complete = completeness(op)
    liq = numeric_feature(op, "liquidity_usd")
    prior = _liquidity_prior(liq, cfg)
    risk = creator_funder_risk(op, cfg.risk_weights, cfg.hard_gates.confirmed_rug_link_min_identity_confidence)
    reasons = []
    model_p = None
    version = "rules-only-v1"
    if bundle:
        model_p = float(bundle.pipeline.predict_proba(feature_frame([op]))[0,1])
        base = 100.0 * ((cfg.model_weight*model_p + cfg.liquidity_prior_weight*(prior/100.0)) / (cfg.model_weight + cfg.liquidity_prior_weight))
        version = bundle.version
    else:
        base = _rules_quality(op, prior)
        reasons.append("rules-only fallback: train and provide a model before relying on ML probability")
    score = max(0.0, min(100.0, base - cfg.risk_penalty_weight*risk.score))
    gate_reasons = _hard_gate_reasons(op, cfg)
    reasons.extend(risk.reasons)
    if missing:
        decision = "INSUFFICIENT_DATA"; reasons.append("missing required features: " + ", ".join(missing))
    elif complete < cfg.thresholds.minimum_feature_completeness:
        decision = "INSUFFICIENT_DATA"; reasons.append("feature completeness below configured threshold")
    elif gate_reasons:
        decision = "REJECT"; reasons.extend(gate_reasons)
    elif risk.confirmed_malicious_link or risk.score >= cfg.thresholds.hard_reject_risk:
        decision = "REJECT"; reasons.append("creator/funder risk meets hard-reject policy")
    elif score >= cfg.thresholds.accept_score:
        decision = "ACCEPT"; reasons.append("score meets configured accept threshold")
    elif score >= cfg.thresholds.review_score:
        decision = "REVIEW"; reasons.append("score is in configured review band")
    else:
        decision = "REJECT"; reasons.append("score is below configured review threshold")
    if cfg.preferred_liquidity_low_usd <= liq < cfg.preferred_liquidity_high_usd:
        reasons.append("liquidity is in the evidence-priority $50K-$75K research band")
    elif cfg.excluded_research_band_low_usd <= liq < cfg.excluded_research_band_high_usd:
        reasons.append("liquidity is in the historically weak $150K-$200K research band")
    return ScoreResult(opportunity_id=op.opportunity_id, mint=op.mint, pool=op.pool, decision_ts=op.decision_ts, decision=decision, score=round(score,4), model_probability=None if model_p is None else round(model_p,6), liquidity_prior=prior, creator_funder_risk_score=risk.score, feature_completeness=round(complete,4), reasons=reasons, model_version=version)

def score_many(rows: list[Opportunity], config: AppConfig, bundle: ModelBundle | None = None) -> list[ScoreResult]:
    return [score_opportunity(o, config, bundle) for o in rows]
