from __future__ import annotations
import math
import numpy as np
import pandas as pd
from .models import Opportunity

FEATURE_NAMES = [
    "liquidity_usd", "pool_lifetime_swaps", "graduation_age_seconds",
    "signal_age_seconds", "quote_age_seconds", "buy_price_impact_pct",
    "immediate_round_trip_loss_pct", "unique_buyers_30s",
    "buy_sell_notional_ratio_30s", "top_buyer_cluster_share_pct",
    "top1_holder_share_pct", "top10_holder_share_pct",
    "reserve_decline_30s_pct", "creator_cluster_sale_supply_pct_30s",
    "creator_prior_confirmed_rug_count_30d",
    "funder_prior_confirmed_rug_count_30d", "malicious_link_recency_days",
    "identity_confidence", "sell_route_available", "mint_authority_safe",
    "freeze_authority_safe",
]

def numeric_feature(opportunity: Opportunity, name: str) -> float:
    obs = opportunity.features.get(name)
    if obs is None or obs.value is None:
        return float("nan")
    if isinstance(obs.value, bool):
        return float(obs.value)
    if isinstance(obs.value, (int, float)):
        value = float(obs.value)
        return value if math.isfinite(value) else float("nan")
    return float("nan")

def feature_frame(opportunities: list[Opportunity]) -> pd.DataFrame:
    return pd.DataFrame([{name: numeric_feature(o, name) for name in FEATURE_NAMES} for o in opportunities], columns=FEATURE_NAMES)

def completeness(opportunity: Opportunity) -> float:
    present = sum(not np.isnan(numeric_feature(opportunity, name)) for name in FEATURE_NAMES)
    return present / len(FEATURE_NAMES)

def missing_required(opportunity: Opportunity, required: list[str]) -> list[str]:
    return [name for name in required if np.isnan(numeric_feature(opportunity, name))]
