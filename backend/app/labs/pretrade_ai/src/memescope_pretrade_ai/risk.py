from __future__ import annotations
from dataclasses import dataclass
from .config import RiskWeights
from .features import numeric_feature
from .models import Opportunity

@dataclass(frozen=True)
class RiskResult:
    score: float
    completeness: float
    reasons: list[str]
    confirmed_malicious_link: bool

def creator_funder_risk(op: Opportunity, weights: RiskWeights, confidence_gate: float = 0.70) -> RiskResult:
    creator = numeric_feature(op, "creator_prior_confirmed_rug_count_30d")
    funder = numeric_feature(op, "funder_prior_confirmed_rug_count_30d")
    recency = numeric_feature(op, "malicious_link_recency_days")
    confidence = numeric_feature(op, "identity_confidence")
    sale = numeric_feature(op, "creator_cluster_sale_supply_pct_30s")
    reserve = numeric_feature(op, "reserve_decline_30s_pct")
    values = [creator, funder, recency, confidence, sale, reserve]
    known = sum(v == v for v in values)
    reasons: list[str] = []
    risk = 0.0
    conf = confidence if confidence == confidence else 0.0
    if creator == creator and creator > 0:
        risk += min(1.0, creator) * weights.creator_confirmed_rug * conf
        reasons.append("creator cluster has a prior confirmed-rug link known before entry")
    if funder == funder and funder > 0:
        risk += min(1.0, funder) * weights.funder_confirmed_rug * conf
        reasons.append("funder cluster has a prior confirmed-rug link known before entry")
    if recency == recency and recency <= 30 and (creator > 0 or funder > 0):
        risk += weights.recent_link * max(0.0, 1.0 - recency / 30.0) * conf
        reasons.append("malicious-link evidence is recent")
    if sale == sale and sale > 0:
        risk += weights.creator_sale * min(1.0, sale / weights.creator_sale_reference_pct)
        if sale >= weights.creator_sale_reference_pct:
            reasons.append("creator-cluster pre-entry selling meets the research reference")
    if reserve == reserve and reserve > 0:
        risk += weights.reserve_decline * min(1.0, reserve / weights.reserve_decline_reference_pct)
        if reserve >= weights.reserve_decline_reference_pct:
            reasons.append("pre-entry quote-reserve deterioration is elevated")
    if confidence != confidence:
        risk += weights.missing_identity
        reasons.append("identity confidence is missing; missing is not treated as safe")
    confirmed = conf >= confidence_gate and ((creator == creator and creator > 0) or (funder == funder and funder > 0))
    return RiskResult(round(min(100.0, risk), 4), known / len(values), reasons, confirmed)
