"""Reason codes rendered into English, on the backend.

The frontend never composes these sentences. That rule was established when
`lib/intelligence.ts` was deleted in Phase 4.1 — a second opinion about the same
token, rendered client-side, can disagree with the engine that produced it.
Sentinel narrates what arrives here; it does not write it.

Templates are indicative, not predictive: "liquidity has grown", never
"liquidity will grow".
"""

from __future__ import annotations

from app.radar.models import RadarDimension, RadarReason

#: Which division owns each readout, matching the existing agent identities.
REASON_AGENT: dict[RadarReason, str] = {
    RadarReason.LIQUIDITY_GROWING: "sentinel",
    RadarReason.LIQUIDITY_SHRINKING: "sentinel",
    RadarReason.VOLUME_EXPANDING: "pulse",
    RadarReason.VOLUME_FADING: "pulse",
    RadarReason.PRICE_TRENDING_UP: "pulse",
    RadarReason.PRICE_TRENDING_DOWN: "pulse",
    RadarReason.BUY_PRESSURE_DOMINANT: "pulse",
    RadarReason.SELL_PRESSURE_DOMINANT: "pulse",
    RadarReason.HIGHER_HIGHS_AND_LOWS: "oracle",
    RadarReason.RESISTANCE_BROKEN: "oracle",
    RadarReason.TREND_ALIGNED: "oracle",
    RadarReason.VOLATILITY_COMPRESSED: "oracle",
    RadarReason.STRUCTURE_BREAKING_DOWN: "oracle",
    RadarReason.LIQUIDITY_DEEP_FOR_SIZE: "sentinel",
    RadarReason.LIQUIDITY_THIN_FOR_SIZE: "sentinel",
    RadarReason.TURNOVER_HEALTHY: "oracle",
    RadarReason.LIQUIDITY_CRITICALLY_THIN: "sentinel",
    RadarReason.VOLUME_WITHOUT_LIQUIDITY: "sentinel",
    RadarReason.INSUFFICIENT_HISTORY: "scout",
    RadarReason.SIGNAL_NOT_AVAILABLE: "oracle",
    RadarReason.COMMUNITY_DATA_UNAVAILABLE: "echo",
}

REASON_SEVERITY: dict[RadarReason, str] = {
    RadarReason.LIQUIDITY_GROWING: "positive",
    RadarReason.LIQUIDITY_SHRINKING: "caution",
    RadarReason.VOLUME_EXPANDING: "positive",
    RadarReason.VOLUME_FADING: "caution",
    RadarReason.PRICE_TRENDING_UP: "positive",
    RadarReason.PRICE_TRENDING_DOWN: "caution",
    RadarReason.BUY_PRESSURE_DOMINANT: "positive",
    RadarReason.SELL_PRESSURE_DOMINANT: "caution",
    RadarReason.HIGHER_HIGHS_AND_LOWS: "positive",
    RadarReason.RESISTANCE_BROKEN: "positive",
    RadarReason.TREND_ALIGNED: "positive",
    RadarReason.VOLATILITY_COMPRESSED: "info",
    RadarReason.STRUCTURE_BREAKING_DOWN: "caution",
    RadarReason.LIQUIDITY_DEEP_FOR_SIZE: "positive",
    RadarReason.LIQUIDITY_THIN_FOR_SIZE: "caution",
    RadarReason.TURNOVER_HEALTHY: "positive",
    RadarReason.LIQUIDITY_CRITICALLY_THIN: "critical",
    RadarReason.VOLUME_WITHOUT_LIQUIDITY: "critical",
    RadarReason.INSUFFICIENT_HISTORY: "info",
    RadarReason.SIGNAL_NOT_AVAILABLE: "info",
    RadarReason.COMMUNITY_DATA_UNAVAILABLE: "info",
}

REASON_MESSAGE: dict[RadarReason, str] = {
    RadarReason.LIQUIDITY_GROWING: "Liquidity has grown across the observation window.",
    RadarReason.LIQUIDITY_SHRINKING: "Liquidity has been withdrawn over the window.",
    RadarReason.VOLUME_EXPANDING: "Trading volume is expanding against its own baseline.",
    RadarReason.VOLUME_FADING: "Trading volume is fading against its own baseline.",
    RadarReason.PRICE_TRENDING_UP: "Price has trended up across the window.",
    RadarReason.PRICE_TRENDING_DOWN: "Price has trended down across the window.",
    RadarReason.BUY_PRESSURE_DOMINANT: "Buys outnumber sells over the last day.",
    RadarReason.SELL_PRESSURE_DOMINANT: "Sells outnumber buys over the last day.",
    RadarReason.HIGHER_HIGHS_AND_LOWS: "Successive highs and lows are both rising.",
    RadarReason.RESISTANCE_BROKEN: "Price has moved above its prior observed high.",
    RadarReason.TREND_ALIGNED: "Short-term average is holding above the longer one.",
    RadarReason.VOLATILITY_COMPRESSED: "The observed range has narrowed.",
    RadarReason.STRUCTURE_BREAKING_DOWN: "Successive highs and lows are both falling.",
    RadarReason.LIQUIDITY_DEEP_FOR_SIZE: "Liquidity is deep relative to the valuation.",
    RadarReason.LIQUIDITY_THIN_FOR_SIZE: "Liquidity is thin relative to the valuation.",
    RadarReason.TURNOVER_HEALTHY: "Daily volume is proportionate to pool depth.",
    RadarReason.LIQUIDITY_CRITICALLY_THIN: "Liquidity is too thin to support an exit.",
    RadarReason.VOLUME_WITHOUT_LIQUIDITY: "Volume far exceeds the liquidity behind it.",
    RadarReason.INSUFFICIENT_HISTORY: "Too few observations to read a trend yet.",
    RadarReason.SIGNAL_NOT_AVAILABLE: "This signal is not available for this token.",
    RadarReason.COMMUNITY_DATA_UNAVAILABLE: (
        "Community signals are declared but not yet collected."
    ),
}

DIMENSION_LABEL: dict[RadarDimension, str] = {
    RadarDimension.ONCHAIN_HEALTH: "On-chain health",
    RadarDimension.MOMENTUM: "Momentum",
    RadarDimension.TECHNICAL: "Technical strength",
    RadarDimension.LIQUIDITY_QUALITY: "Liquidity quality",
    RadarDimension.COMMUNITY: "Community",
    RadarDimension.RISK: "Risk",
}


def render(reason: RadarReason) -> dict[str, str]:
    """One reason as the API serves it."""
    return {
        "code": reason.value,
        "agent": REASON_AGENT[reason],
        "severity": REASON_SEVERITY[reason],
        "message": REASON_MESSAGE[reason],
    }
