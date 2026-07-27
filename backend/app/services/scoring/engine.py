"""The scoring engine.

`evaluate(feature_set, model_config)` is the whole public surface. It performs no
I/O: no database, no network, no clock, no randomness. Time enters only through
`FeatureSet.evaluated_at`, which the caller supplies, exactly as
`RefreshScheduler.decide()` takes `now` rather than reading it.

That purity is not stylistic. It buys, at no cost: exact backfill of any
historical score, shadow evaluation of a candidate model over the same features,
unit tests with no fixtures, and a later ML combiner that replaces one function
instead of a subsystem.

Reproducibility is a three-tier contract:

  * **Tier 1, strongly reproducible.** `score`, `market_risk`, `evidence`,
    `coverage`, `grade`, and every contribution depend only on the feature set
    and the model. No dependence on any prior score.
  * **Tier 2, replay-reproducible.** `is_elite` and `elite_streak` depend on
    sustained qualification. The prior streak arrives as an input derived from
    stored history, so replaying history in evaluation order reproduces them.
  * **Tier 3, never stored.** Freshness and the served confidence are computed
    at read time and do not appear here at all.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, localcontext

from app.models.score import ScoreGrade
from app.services.scoring.components import COMPONENT_REGISTRY, RISK_GATE
from app.services.scoring.components.base import ComponentId, ComponentResult
from app.services.scoring.components.market_risk import MarketRisk, RiskAssessment
from app.services.scoring.evidence import EvidenceAssessment, assess
from app.services.scoring.explain import Explanation, ReasonCode, build_explanation
from app.services.scoring.features import FeatureSet
from app.services.scoring.grading import elite_status, grade_for, qualifies_for_elite
from app.services.scoring.models.base import ModelConfig
from app.services.scoring.normalisers import (
    HUNDRED,
    ONE,
    SCORING_CONTEXT,
    ZERO,
    clamp,
    quantize,
)
from app.services.scoring.weighting import solve_weights

#: Minimum observations before window-based signals count as deep. Mirrors
#: `SCORING_MIN_OBSERVATIONS`; passed explicitly so `evaluate` reads no settings.
DEFAULT_MIN_OBSERVATIONS = 3


@dataclass(frozen=True, slots=True)
class ComponentBreakdown:
    """One component's line in the score's waterfall.

    `contribution` is in final score points and is quantised such that the
    contributions sum exactly to `opportunity_raw` - see `_quantise_contributions`.
    """

    id: ComponentId
    agent: str
    available: bool
    score: Decimal | None
    declared_weight: Decimal
    effective_weight: Decimal
    contribution: Decimal
    raw: Mapping[str, Decimal | None]
    reasons: tuple[ReasonCode, ...]


@dataclass(frozen=True, slots=True)
class ScoreResult:
    """Everything one evaluation produces."""

    mint_address: str
    model_version: str
    scorable: bool

    score: Decimal
    opportunity_raw: Decimal
    market_risk: Decimal
    risk_deduction: Decimal
    evidence: Decimal
    coverage: Decimal
    observations: int

    grade: ScoreGrade
    is_elite: bool
    elite_streak: int
    has_veto: bool

    components: tuple[ComponentBreakdown, ...]
    explanation: Explanation
    reasons: tuple[ReasonCode, ...] = field(default_factory=tuple)

    @property
    def reconciles(self) -> bool:
        """Contributions minus the risk deduction equal the score, exactly.

        Asserted in tests rather than at runtime; it is a property of the
        quantisation rule, not a condition that can fail on valid input.
        """
        total = sum((entry.contribution for entry in self.components), start=ZERO)
        return total - self.risk_deduction == self.score


def evaluate(
    feature_set: FeatureSet,
    model_config: ModelConfig,
    *,
    min_observations: int = DEFAULT_MIN_OBSERVATIONS,
    risk_gate: MarketRisk | None = None,
) -> ScoreResult:
    """Score one token. Pure, deterministic, and free of I/O.

    The whole body runs inside `SCORING_CONTEXT`. `decimal.getcontext()` is
    thread-local and mutable by anything else in the process, so evaluating
    under the ambient context would make output depend on what ran before -
    which is precisely what "deterministic" must rule out.
    """
    with localcontext(SCORING_CONTEXT):
        return _evaluate(feature_set, model_config, min_observations, risk_gate or RISK_GATE)


def _evaluate(
    features: FeatureSet,
    config: ModelConfig,
    min_observations: int,
    risk_gate: MarketRisk,
) -> ScoreResult:
    declared = config.declared_weights
    results = _run_components(features, config)

    available = [result for result in results if result.available]
    available_weight = sum((declared[result.id] for result in available), start=ZERO)

    evidence = assess(
        results,
        declared,
        observations=features.observations,
        required_observations=min_observations,
    )
    risk = risk_gate.evaluate(features)

    if available_weight < config.min_scorable_weight:
        # Too little to say anything honest. Declining is the point: a score
        # built from one component would be indistinguishable, downstream, from
        # a score built from all of them.
        return _insufficient(features, config, results, declared, evidence, risk)

    solution = solve_weights(
        {result.id: declared[result.id] for result in available},
        config.max_single_contribution,
    )

    contributions = {
        result.id: solution.weights[result.id] * (result.score or ZERO) for result in available
    }
    opportunity = sum(contributions.values(), start=ZERO)

    gated = opportunity * (ONE - config.risk_lambda * risk.penalty)
    if risk.vetoed:
        gated = min(gated, config.veto_ceiling)
    score = clamp(gated)

    opportunity_q = quantize(clamp(opportunity))
    score_q = quantize(score)
    # Defined as the residual rather than rounded independently, which is what
    # makes the waterfall add up exactly (design section 8.4).
    risk_deduction_q = opportunity_q - score_q

    breakdowns = _build_breakdowns(
        results, declared, solution.weights, contributions, opportunity_q
    )

    grade = grade_for(score_q, config.grade_bands)
    qualifies = qualifies_for_elite(
        score=score_q,
        evidence=evidence.evidence,
        risk_penalty=risk.penalty,
        liquidity_usd=features.liquidity_usd,
        vetoed=risk.vetoed,
        gate=config.elite_gate,
    )
    is_elite, streak = elite_status(
        qualifies=qualifies,
        prior_streak=features.prior_elite_streak,
        gate=config.elite_gate,
    )
    if risk.vetoed:
        grade = ScoreGrade.CRITICAL

    codes = _collect_reasons(
        results, risk, evidence.limiting_reason, solution.cap_relaxed, qualifies, is_elite
    )
    explanation = build_explanation(codes)

    return ScoreResult(
        mint_address=features.mint_address,
        model_version=config.version,
        scorable=True,
        score=score_q,
        opportunity_raw=opportunity_q,
        market_risk=quantize(clamp(risk.as_score)),
        risk_deduction=risk_deduction_q,
        evidence=quantize(evidence.evidence),
        coverage=quantize(evidence.coverage_score),
        observations=features.observations,
        grade=grade,
        is_elite=is_elite,
        elite_streak=streak,
        has_veto=risk.vetoed,
        components=breakdowns,
        explanation=explanation,
        reasons=explanation.reasons,
    )


def _run_components(features: FeatureSet, config: ModelConfig) -> list[ComponentResult]:
    """Evaluate every declared component, isolating failures to one component.

    A component raising must not cost the whole score. The failure becomes an
    unavailable result, which charges its weight to coverage and shows up in the
    explanation - degraded, visible, and still useful.
    """
    results: list[ComponentResult] = []
    for entry in config.components:
        component = COMPONENT_REGISTRY[entry.id]
        try:
            result = component.evaluate(features)
        except Exception:
            results.append(
                ComponentResult.unavailable(
                    entry.id, component.agent, reason=ReasonCode.COMPONENT_ERROR
                )
            )
            continue

        if result.available and result.score is None:
            # A component claiming availability with no score would poison the
            # weighted sum; treat the contract violation as unavailability.
            results.append(
                ComponentResult.unavailable(
                    entry.id, component.agent, reason=ReasonCode.COMPONENT_ERROR
                )
            )
            continue

        results.append(
            result
            if not result.available
            else ComponentResult(
                id=result.id,
                agent=result.agent,
                available=True,
                score=clamp(result.score or ZERO),
                raw=result.raw,
                reasons=result.reasons,
            )
        )
    return results


def _quantise_contributions(
    raw: Sequence[tuple[ComponentId, Decimal]], target: Decimal
) -> dict[ComponentId, Decimal]:
    """Quantise contributions so they sum to `target` exactly.

    Rounding each contribution independently leaves a residual of a cent or two
    against the separately-rounded total, which would make the waterfall fail to
    add up on screen. The largest contribution absorbs it - largest because a
    one-cent adjustment is proportionally least visible there.

    Ties are broken by component id so the choice is deterministic; leaving it to
    iteration order would make the same inputs reconcile differently run to run.
    """
    quantised = {component_id: quantize(value) for component_id, value in raw}
    if not quantised:
        return quantised

    residual = target - sum(quantised.values(), start=ZERO)
    if residual != ZERO:
        largest = max(quantised, key=lambda key: (quantised[key], key))
        quantised[largest] += residual
    return quantised


def _build_breakdowns(
    results: Sequence[ComponentResult],
    declared: Mapping[ComponentId, Decimal],
    weights: Mapping[ComponentId, Decimal],
    contributions: Mapping[ComponentId, Decimal],
    opportunity: Decimal,
) -> tuple[ComponentBreakdown, ...]:
    quantised = _quantise_contributions(list(contributions.items()), opportunity)
    return tuple(
        ComponentBreakdown(
            id=result.id,
            agent=str(result.agent),
            available=result.available,
            score=quantize(result.score) if result.score is not None else None,
            declared_weight=declared[result.id],
            effective_weight=weights.get(result.id, ZERO),
            contribution=quantised.get(result.id, ZERO),
            raw=result.raw,
            reasons=result.reasons,
        )
        for result in results
    )


def _collect_reasons(
    results: Sequence[ComponentResult],
    risk: RiskAssessment,
    limiting: ReasonCode | None,
    cap_relaxed: bool,
    qualifies_elite: bool,
    is_elite: bool,
) -> tuple[ReasonCode, ...]:
    """Gather every code emitted this evaluation, in emission order.

    Ordering by severity happens in `build_explanation`; here the only
    requirement is that the sequence is deterministic, which it is because
    components are visited in the model's declared order.
    """
    codes: list[ReasonCode] = []
    for result in results:
        codes.extend(result.reasons)
    codes.extend(risk.reasons)
    if cap_relaxed:
        codes.append(ReasonCode.WEIGHT_CAP_RELAXED)
    if limiting is not None:
        codes.append(limiting)
    if is_elite:
        codes.append(ReasonCode.ELITE_SUSTAINED)
    elif qualifies_elite:
        codes.append(ReasonCode.ELITE_PENDING_SUSTAIN)
    return tuple(codes)


def _insufficient(
    features: FeatureSet,
    config: ModelConfig,
    results: Sequence[ComponentResult],
    declared: Mapping[ComponentId, Decimal],
    evidence: EvidenceAssessment,
    risk: RiskAssessment,
) -> ScoreResult:
    """The "we decline to score this" result.

    Still a full result rather than `None`: the caller needs the reasons and the
    coverage figure to explain the absence, and a null would force every consumer
    to invent its own account of why.
    """
    codes = _collect_reasons(results, risk, None, False, False, False)
    explanation = build_explanation((*codes, ReasonCode.INSUFFICIENT_DATA))

    breakdowns = _build_breakdowns(results, declared, {}, {}, ZERO)

    return ScoreResult(
        mint_address=features.mint_address,
        model_version=config.version,
        scorable=False,
        score=ZERO,
        opportunity_raw=ZERO,
        market_risk=quantize(clamp(risk.as_score)),
        risk_deduction=ZERO,
        evidence=ZERO,
        coverage=quantize(clamp(evidence.coverage_score, ZERO, HUNDRED)),
        observations=features.observations,
        grade=ScoreGrade.CRITICAL,
        is_elite=False,
        elite_streak=0,
        has_veto=risk.vetoed,
        components=breakdowns,
        explanation=explanation,
        reasons=explanation.reasons,
    )
