"""Reason codes and the structured explanation built from them.

The engine emits codes, never prose. Presentation templates live here beside the
codes so a reader can see what each one will say, but rendering is the API
layer's job - the engine never returns a sentence.

That split is what makes explanations testable, translatable, and diffable
across model versions, and it keeps generation cost out of a path that runs tens
of thousands of times an hour.

**Codes are append-only.** They are persisted in `token_score_history.reasons`,
so removing or repurposing one silently rewrites the meaning of stored history.
Adding is always safe.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class AgentId(enum.StrEnum):
    """The AI division that owns a readout.

    Every reason belongs to an agent so the Observatory Log can attribute it -
    "Sentinel detected liquidity withdrawal" is generated from a code plus its
    owner, not from a sentence the engine guessed at.
    """

    SCOUT = "scout"
    TITAN = "titan"
    ORACLE = "oracle"
    PULSE = "pulse"
    SENTINEL = "sentinel"
    ECHO = "echo"
    APEX = "apex"


class Severity(enum.StrEnum):
    """How loudly a reason should be presented.

    Ordering matters: the highest-severity reason becomes the headline, so the
    rank is explicit rather than relying on declaration order.
    """

    INFO = "info"
    POSITIVE = "positive"
    CAUTION = "caution"
    CRITICAL = "critical"


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.INFO: 0,
    Severity.POSITIVE: 1,
    Severity.CAUTION: 2,
    Severity.CRITICAL: 3,
}


class ReasonCode(enum.StrEnum):
    """Stable, persisted identifiers for why a score reads as it does."""

    # --- Liquidity (Sentinel) ------------------------------------------------
    LIQUIDITY_DEEP = "LIQUIDITY_DEEP"
    LIQUIDITY_ADEQUATE = "LIQUIDITY_ADEQUATE"
    LIQUIDITY_THIN = "LIQUIDITY_THIN"
    LIQUIDITY_DRAWDOWN_ACUTE = "LIQUIDITY_DRAWDOWN_ACUTE"
    LIQUIDITY_DRAWDOWN_GRADUAL = "LIQUIDITY_DRAWDOWN_GRADUAL"
    DEPTH_RATIO_CRITICAL = "DEPTH_RATIO_CRITICAL"
    DEPTH_RATIO_UNAVAILABLE = "DEPTH_RATIO_UNAVAILABLE"

    # --- Momentum and flow (Pulse) -------------------------------------------
    MOMENTUM_ACCELERATING = "MOMENTUM_ACCELERATING"
    MOMENTUM_STEADY = "MOMENTUM_STEADY"
    MOMENTUM_DECAYING = "MOMENTUM_DECAYING"
    MOMENTUM_COARSE_SAMPLING = "MOMENTUM_COARSE_SAMPLING"
    BUY_PRESSURE_DOMINANT = "BUY_PRESSURE_DOMINANT"
    SELL_PRESSURE_DOMINANT = "SELL_PRESSURE_DOMINANT"
    PARTICIPATION_THIN = "PARTICIPATION_THIN"

    # --- Valuation (Oracle) ---------------------------------------------------
    SUPPLY_OVERHANG = "SUPPLY_OVERHANG"
    VALUATION_COHERENT = "VALUATION_COHERENT"
    VALUATION_IMPLAUSIBLE = "VALUATION_IMPLAUSIBLE"

    # --- Lifecycle (Scout) ----------------------------------------------------
    TOKEN_TOO_NEW = "TOKEN_TOO_NEW"
    SURVIVAL_ESTABLISHED = "SURVIVAL_ESTABLISHED"
    TOKEN_STALE = "TOKEN_STALE"

    # --- Contract and market state (Sentinel) --------------------------------
    POOL_INACTIVE = "POOL_INACTIVE"
    METADATA_UNRESOLVED = "METADATA_UNRESOLVED"

    # --- Engine bookkeeping (Oracle) -----------------------------------------
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    COMPONENT_NOT_YET_IMPLEMENTED = "COMPONENT_NOT_YET_IMPLEMENTED"
    COMPONENT_ERROR = "COMPONENT_ERROR"
    WEIGHT_CAP_RELAXED = "WEIGHT_CAP_RELAXED"
    CONFIDENCE_LIMITED_BY_COVERAGE = "CONFIDENCE_LIMITED_BY_COVERAGE"
    CONFIDENCE_LIMITED_BY_HISTORY = "CONFIDENCE_LIMITED_BY_HISTORY"

    # --- Certification (Apex) -------------------------------------------------
    ELITE_SUSTAINED = "ELITE_SUSTAINED"
    ELITE_PENDING_SUSTAIN = "ELITE_PENDING_SUSTAIN"


@dataclass(frozen=True, slots=True)
class ReasonMeta:
    severity: Severity
    agent: AgentId
    template: str


REASON_META: dict[ReasonCode, ReasonMeta] = {
    ReasonCode.LIQUIDITY_DEEP: ReasonMeta(
        Severity.POSITIVE, AgentId.SENTINEL, "Liquidity depth is substantial."
    ),
    ReasonCode.LIQUIDITY_ADEQUATE: ReasonMeta(
        Severity.INFO, AgentId.SENTINEL, "Liquidity is sufficient to trade."
    ),
    ReasonCode.LIQUIDITY_THIN: ReasonMeta(
        Severity.CAUTION, AgentId.SENTINEL, "Liquidity is thin. Exit risk elevated."
    ),
    ReasonCode.LIQUIDITY_DRAWDOWN_ACUTE: ReasonMeta(
        Severity.CRITICAL,
        AgentId.SENTINEL,
        "Liquidity is being withdrawn rapidly.",
    ),
    ReasonCode.LIQUIDITY_DRAWDOWN_GRADUAL: ReasonMeta(
        Severity.CAUTION, AgentId.SENTINEL, "Liquidity has declined over time."
    ),
    ReasonCode.DEPTH_RATIO_CRITICAL: ReasonMeta(
        Severity.CRITICAL,
        AgentId.SENTINEL,
        "Liquidity is negligible against the valuation.",
    ),
    ReasonCode.DEPTH_RATIO_UNAVAILABLE: ReasonMeta(
        Severity.INFO, AgentId.SENTINEL, "No valuation to measure depth against."
    ),
    ReasonCode.MOMENTUM_ACCELERATING: ReasonMeta(
        Severity.POSITIVE, AgentId.PULSE, "Momentum is increasing rapidly."
    ),
    ReasonCode.MOMENTUM_STEADY: ReasonMeta(
        Severity.INFO, AgentId.PULSE, "Velocity is holding steady."
    ),
    ReasonCode.MOMENTUM_DECAYING: ReasonMeta(
        Severity.CAUTION, AgentId.PULSE, "Momentum is decaying."
    ),
    ReasonCode.MOMENTUM_COARSE_SAMPLING: ReasonMeta(
        Severity.INFO,
        AgentId.PULSE,
        "Observations are widely spaced; trend is approximate.",
    ),
    ReasonCode.BUY_PRESSURE_DOMINANT: ReasonMeta(
        Severity.POSITIVE, AgentId.PULSE, "Buy pressure dominates."
    ),
    ReasonCode.SELL_PRESSURE_DOMINANT: ReasonMeta(
        Severity.CAUTION, AgentId.PULSE, "Sell pressure dominates."
    ),
    ReasonCode.PARTICIPATION_THIN: ReasonMeta(
        Severity.CAUTION, AgentId.PULSE, "Too few trades to read intent."
    ),
    ReasonCode.SUPPLY_OVERHANG: ReasonMeta(
        Severity.CAUTION, AgentId.ORACLE, "Large share of supply is not yet circulating."
    ),
    ReasonCode.VALUATION_COHERENT: ReasonMeta(
        Severity.INFO, AgentId.ORACLE, "Circulating supply matches the valuation."
    ),
    ReasonCode.VALUATION_IMPLAUSIBLE: ReasonMeta(
        Severity.CAUTION, AgentId.ORACLE, "Valuation is implausible for this age."
    ),
    ReasonCode.TOKEN_TOO_NEW: ReasonMeta(
        Severity.INFO, AgentId.SCOUT, "Too new to assess. Monitoring."
    ),
    ReasonCode.SURVIVAL_ESTABLISHED: ReasonMeta(
        Severity.POSITIVE, AgentId.SCOUT, "Token has survived its opening window."
    ),
    ReasonCode.TOKEN_STALE: ReasonMeta(
        Severity.INFO, AgentId.SCOUT, "Token is past its active window."
    ),
    ReasonCode.POOL_INACTIVE: ReasonMeta(
        Severity.CRITICAL, AgentId.SENTINEL, "Pool is no longer trading."
    ),
    ReasonCode.METADATA_UNRESOLVED: ReasonMeta(
        Severity.CAUTION, AgentId.SENTINEL, "Token metadata has not resolved."
    ),
    ReasonCode.INSUFFICIENT_HISTORY: ReasonMeta(
        Severity.INFO, AgentId.ORACLE, "Not enough observations for a trend."
    ),
    ReasonCode.INSUFFICIENT_DATA: ReasonMeta(
        Severity.INFO, AgentId.ORACLE, "Too little data to score this token."
    ),
    ReasonCode.COMPONENT_NOT_YET_IMPLEMENTED: ReasonMeta(
        Severity.INFO, AgentId.ORACLE, "This signal is not yet available."
    ),
    ReasonCode.COMPONENT_ERROR: ReasonMeta(
        Severity.CAUTION, AgentId.ORACLE, "A signal failed to evaluate."
    ),
    ReasonCode.WEIGHT_CAP_RELAXED: ReasonMeta(
        Severity.INFO, AgentId.ORACLE, "Too few signals to apply the usual weighting."
    ),
    ReasonCode.CONFIDENCE_LIMITED_BY_COVERAGE: ReasonMeta(
        Severity.INFO, AgentId.ORACLE, "Confidence is limited by missing signals."
    ),
    ReasonCode.CONFIDENCE_LIMITED_BY_HISTORY: ReasonMeta(
        Severity.INFO, AgentId.ORACLE, "Confidence is limited by short history."
    ),
    ReasonCode.ELITE_SUSTAINED: ReasonMeta(
        Severity.POSITIVE, AgentId.APEX, "Elite classification granted."
    ),
    ReasonCode.ELITE_PENDING_SUSTAIN: ReasonMeta(
        Severity.INFO, AgentId.APEX, "Elite criteria met; awaiting confirmation."
    ),
}


def meta_for(code: ReasonCode) -> ReasonMeta:
    """Look up a code's presentation metadata.

    Every member of the enum has an entry - an invariant test asserts it - so a
    missing key is a programming error, not a runtime condition to handle.
    """
    return REASON_META[code]


@dataclass(frozen=True, slots=True)
class Explanation:
    """The engine's structured account of a score.

    `reasons` is ordered most severe first, with ties broken by the order the
    codes were emitted, so the sequence is stable across runs and the headline
    never depends on dictionary iteration order.
    """

    reasons: tuple[ReasonCode, ...]
    primary: ReasonCode | None

    @property
    def primary_agent(self) -> AgentId | None:
        """Which division owns the headline. Drives Observatory Log attribution."""
        return None if self.primary is None else meta_for(self.primary).agent

    @property
    def primary_severity(self) -> Severity | None:
        return None if self.primary is None else meta_for(self.primary).severity


def build_explanation(codes: tuple[ReasonCode, ...]) -> Explanation:
    """Order and de-duplicate reason codes into an explanation.

    De-duplication keeps first occurrence: a code emitted by both a component
    and the risk gate should appear once, at the position it was first earned.
    """
    seen: dict[ReasonCode, int] = {}
    for index, code in enumerate(codes):
        if code not in seen:
            seen[code] = index

    ordered = sorted(
        seen,
        key=lambda code: (-_SEVERITY_RANK[meta_for(code).severity], seen[code]),
    )
    return Explanation(reasons=tuple(ordered), primary=ordered[0] if ordered else None)
