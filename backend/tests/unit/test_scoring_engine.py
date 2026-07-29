"""Engine tests: the contract `evaluate()` promises.

Three properties carry the most weight here:

  * **Exact reconciliation.** Contributions minus the risk deduction equal the
    score, to the cent. A waterfall that does not add up on screen is a bug the
    user can see.
  * **Determinism.** Same features, same model, same answer - including under a
    hostile ambient `decimal` context, which is thread-local and mutable by any
    code in the process.
  * **Strong reproducibility.** No output in the tier-1 set may depend on a
    prior score.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import ROUND_UP, Context, Decimal, localcontext

import pytest

from app.models.score import ScoreGrade
from app.services.scoring import evaluate
from app.services.scoring.components import COMPONENT_REGISTRY
from app.services.scoring.components.base import (
    ComponentId,
    ComponentResult,
    ScoreComponent,
)
from app.services.scoring.explain import AgentId, ReasonCode, Severity, meta_for
from app.services.scoring.models.base import ComponentWeight, ModelConfig
from app.services.scoring.models.v1 import MODEL_V1
from app.services.scoring.normalisers import HUNDRED, ZERO
from tests.unit.scoring_builders import declining_window, features, observations

pytestmark = pytest.mark.unit

AVAILABLE_IDS = (
    ComponentId.LIQUIDITY_DEPTH,
    ComponentId.MOMENTUM,
    ComponentId.TRADE_FLOW,
    ComponentId.VALUATION_STRUCTURE,
    ComponentId.SURVIVAL_AGE,
)

#: A model whose every component has a data source, used to prove the paths that
#: v1 deliberately cannot reach (full evidence, and therefore Elite).
COMPLETE_MODEL = ModelConfig(
    version="test-complete",
    components=(
        ComponentWeight(ComponentId.LIQUIDITY_DEPTH, Decimal("0.31")),
        ComponentWeight(ComponentId.MOMENTUM, Decimal("0.23")),
        ComponentWeight(ComponentId.TRADE_FLOW, Decimal("0.18")),
        ComponentWeight(ComponentId.VALUATION_STRUCTURE, Decimal("0.15")),
        ComponentWeight(ComponentId.SURVIVAL_AGE, Decimal("0.13")),
    ),
)


def _excellent() -> object:
    """A token doing everything right, for the paths that need a high score."""
    return features(
        liquidity_usd=Decimal(2000000),
        market_cap=Decimal(4000000),
        fully_diluted_valuation=Decimal(4200000),
        volume_24h=Decimal(288000),
        volume_5m=Decimal(20000),
        volume_1h=Decimal(200000),
        buy_count_24h=4000,
        sell_count_24h=800,
        age_minutes=Decimal(600),
        window=observations(count=12, liquidity=2000000, price="0.002"),
    )


# --- Output surface -----------------------------------------------------------


def test_evaluate_returns_the_documented_outputs() -> None:
    result = evaluate(features(), MODEL_V1)

    assert result.opportunity_raw is not None
    assert result.evidence is not None
    assert isinstance(result.grade, ScoreGrade)
    assert result.explanation is not None
    assert len(result.components) == len(MODEL_V1.components)
    assert result.model_version == "v1"
    assert result.mint_address == "MintTest"


def test_the_breakdown_covers_every_declared_component() -> None:
    """Including the unavailable ones - that is what makes the gap visible."""
    result = evaluate(features(), MODEL_V1)
    assert {entry.id for entry in result.components} == set(MODEL_V1.declared_weights)

    unavailable = [entry for entry in result.components if not entry.available]
    assert {entry.id for entry in unavailable} == {
        ComponentId.CONTRACT_SAFETY,
        ComponentId.HOLDER_DISTRIBUTION,
        ComponentId.SMART_MONEY,
        ComponentId.NARRATIVE,
    }
    assert all(entry.contribution == ZERO for entry in unavailable)
    assert all(entry.declared_weight > ZERO for entry in unavailable)


def test_scores_stay_within_range_across_wildly_different_inputs() -> None:
    candidates = [
        features(),
        _excellent(),
        features(liquidity_usd=None, market_cap=None, volume_24h=None, window=()),
        features(trading_status="inactive"),
        features(liquidity_usd=Decimal(1), market_cap=Decimal(10**9)),
        features(age_minutes=Decimal(10**6)),
        features(buy_count_24h=0, sell_count_24h=10**7),
    ]
    for candidate in candidates:
        result = evaluate(candidate, MODEL_V1)
        assert ZERO <= result.score <= HUNDRED
        assert ZERO <= result.opportunity_raw <= HUNDRED
        assert ZERO <= result.evidence <= HUNDRED
        assert ZERO <= result.market_risk <= HUNDRED


# --- Exact reconciliation -----------------------------------------------------


@pytest.mark.parametrize(
    "candidate",
    [
        features(),
        features(liquidity_usd=Decimal(777), market_cap=Decimal(31337)),
        features(volume_5m=Decimal("123.456"), volume_24h=Decimal("98765.4321")),
        features(buy_count_24h=7, sell_count_24h=13),
        features(metadata_resolved=False),
        features(window=declining_window(peak=90000, current=50000, seconds_ago=600)),
    ],
    ids=["baseline", "odd-liquidity", "odd-volume", "few-trades", "no-metadata", "drawdown"],
)
def test_the_waterfall_adds_up_exactly(candidate: object) -> None:
    """Independently rounded contributions would miss the total by a cent."""
    result = evaluate(candidate, MODEL_V1)  # type: ignore[arg-type]
    total = sum((entry.contribution for entry in result.components), start=ZERO)

    assert total == result.opportunity_raw
    assert total - result.risk_deduction == result.score
    assert result.reconciles


def test_every_stored_figure_is_quantised_to_two_places() -> None:
    result = evaluate(features(), MODEL_V1)
    for value in (
        result.score,
        result.opportunity_raw,
        result.evidence,
        result.coverage,
        result.market_risk,
    ):
        assert value == value.quantize(Decimal("0.01"))


# --- Determinism and reproducibility ------------------------------------------


def test_repeated_evaluation_is_identical() -> None:
    candidate = features()
    first = evaluate(candidate, MODEL_V1)
    second = evaluate(candidate, MODEL_V1)
    assert first == second


def test_a_hostile_ambient_decimal_context_cannot_change_the_result() -> None:
    """`getcontext()` is thread-local and mutable; the engine must not trust it."""
    baseline = evaluate(features(), MODEL_V1)

    with localcontext(Context(prec=6, rounding=ROUND_UP)):
        under_pressure = evaluate(features(), MODEL_V1)

    assert under_pressure == baseline


def test_tier_one_outputs_ignore_the_prior_streak() -> None:
    """Strong reproducibility: no tier-1 field may depend on a previous score."""
    without = evaluate(features(prior_elite_streak=0), MODEL_V1)
    with_streak = evaluate(features(prior_elite_streak=7), MODEL_V1)

    assert without.score == with_streak.score
    assert without.opportunity_raw == with_streak.opportunity_raw
    assert without.evidence == with_streak.evidence
    assert without.coverage == with_streak.coverage
    assert without.market_risk == with_streak.market_risk
    assert without.grade == with_streak.grade
    assert without.components == with_streak.components


def test_evaluation_does_not_mutate_its_input() -> None:
    candidate = features()
    before = replace(candidate)
    evaluate(candidate, MODEL_V1)
    assert candidate == before


# --- Risk gating --------------------------------------------------------------


def test_a_veto_caps_the_score_and_forces_critical() -> None:
    result = evaluate(features(trading_status="inactive"), MODEL_V1)
    assert result.has_veto is True
    assert result.score <= MODEL_V1.veto_ceiling
    assert result.grade is ScoreGrade.CRITICAL
    assert result.is_elite is False


def test_risk_reduces_the_score_below_the_opportunity() -> None:
    risky = features(metadata_resolved=False)
    result = evaluate(risky, MODEL_V1)
    assert result.market_risk > ZERO
    assert result.score < result.opportunity_raw
    assert result.risk_deduction > ZERO


def test_no_risk_means_no_deduction() -> None:
    result = evaluate(features(), MODEL_V1)
    assert result.market_risk == ZERO
    assert result.score == result.opportunity_raw
    assert result.risk_deduction == ZERO


# --- Insufficient data --------------------------------------------------------


def test_a_token_with_almost_nothing_is_not_scored() -> None:
    """Declining beats scoring on one component and looking the same downstream."""
    barren = features(
        liquidity_usd=None,
        market_cap=None,
        fully_diluted_valuation=None,
        volume_24h=None,
        buy_count_24h=None,
        sell_count_24h=None,
        window=(),
    )
    result = evaluate(barren, MODEL_V1)

    assert result.scorable is False
    assert result.score == ZERO
    assert result.evidence == ZERO
    assert result.grade is ScoreGrade.CRITICAL
    assert ReasonCode.INSUFFICIENT_DATA in result.reasons


def test_the_unscorable_result_still_explains_itself() -> None:
    barren = features(
        liquidity_usd=None,
        market_cap=None,
        fully_diluted_valuation=None,
        volume_24h=None,
        buy_count_24h=None,
        sell_count_24h=None,
        window=(),
    )
    result = evaluate(barren, MODEL_V1)

    assert result.explanation.primary is not None
    assert len(result.components) == len(MODEL_V1.components)
    assert result.coverage > ZERO  # survival_age alone is still coverage


def test_survival_alone_falls_under_the_scorable_floor() -> None:
    """0.08 of declared weight is below the 0.15 minimum."""
    assert MODEL_V1.weight_for(ComponentId.SURVIVAL_AGE) < MODEL_V1.min_scorable_weight


# --- Component isolation ------------------------------------------------------


class _Exploding(ScoreComponent):
    id = ComponentId.MOMENTUM
    agent = AgentId.PULSE

    def evaluate(self, features: object) -> ComponentResult:
        raise RuntimeError("provider parsing blew up")


class _Contradictory(ScoreComponent):
    """Claims availability but supplies no score - a contract violation."""

    id = ComponentId.MOMENTUM
    agent = AgentId.PULSE

    def evaluate(self, features: object) -> ComponentResult:
        return ComponentResult(
            id=ComponentId.MOMENTUM, agent=AgentId.PULSE, available=True, score=None
        )


def test_a_raising_component_does_not_cost_the_whole_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(COMPONENT_REGISTRY, ComponentId.MOMENTUM, _Exploding())
    result = evaluate(features(), MODEL_V1)

    assert result.scorable is True
    assert ReasonCode.COMPONENT_ERROR in result.reasons
    momentum = next(e for e in result.components if e.id is ComponentId.MOMENTUM)
    assert momentum.available is False
    # Its weight is charged to coverage rather than silently ignored.
    assert result.coverage < Decimal(65)


def test_an_available_component_with_no_score_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Letting it through would poison the weighted sum with a None."""
    monkeypatch.setitem(COMPONENT_REGISTRY, ComponentId.MOMENTUM, _Contradictory())
    result = evaluate(features(), MODEL_V1)

    momentum = next(e for e in result.components if e.id is ComponentId.MOMENTUM)
    assert momentum.available is False
    assert ReasonCode.COMPONENT_ERROR in result.reasons


# --- Elite --------------------------------------------------------------------


def test_v1_can_never_certify_elite() -> None:
    """Evidence tops out at 65; the gate needs 70. Gold stays dark until Day 6."""
    result = evaluate(
        features(
            liquidity_usd=Decimal(2000000),
            market_cap=Decimal(4000000),
            prior_elite_streak=10,
        ),
        MODEL_V1,
    )
    assert result.evidence <= Decimal(65)
    assert result.is_elite is False


def test_elite_is_reachable_once_every_signal_exists() -> None:
    """Proves the gate works, using a model where nothing is missing."""
    result = evaluate(
        features(
            liquidity_usd=Decimal(2000000),
            market_cap=Decimal(4000000),
            fully_diluted_valuation=Decimal(4200000),
            volume_24h=Decimal(288000),
            volume_5m=Decimal(20000),
            volume_1h=Decimal(200000),
            buy_count_24h=4000,
            sell_count_24h=800,
            age_minutes=Decimal(600),
            window=observations(count=12, liquidity=2000000, price="0.002"),
            prior_elite_streak=2,
        ),
        COMPLETE_MODEL,
    )

    assert result.evidence == HUNDRED
    assert result.score >= COMPLETE_MODEL.elite_gate.min_score
    assert result.is_elite is True
    assert result.elite_streak == 3
    assert ReasonCode.ELITE_SUSTAINED in result.reasons


def test_a_qualifying_token_awaiting_sustain_is_marked_pending() -> None:
    result = evaluate(
        features(
            liquidity_usd=Decimal(2000000),
            market_cap=Decimal(4000000),
            fully_diluted_valuation=Decimal(4200000),
            volume_24h=Decimal(288000),
            volume_5m=Decimal(20000),
            volume_1h=Decimal(200000),
            buy_count_24h=4000,
            sell_count_24h=800,
            age_minutes=Decimal(600),
            window=observations(count=12, liquidity=2000000, price="0.002"),
            prior_elite_streak=0,
        ),
        COMPLETE_MODEL,
    )
    assert result.is_elite is False
    assert ReasonCode.ELITE_PENDING_SUSTAIN in result.reasons


# --- Explanation --------------------------------------------------------------


def test_the_headline_is_the_most_severe_reason() -> None:
    result = evaluate(features(trading_status="inactive"), MODEL_V1)
    assert result.explanation.primary is ReasonCode.POOL_INACTIVE
    assert result.explanation.primary_severity is Severity.CRITICAL
    assert result.explanation.primary_agent is AgentId.SENTINEL


def test_reasons_are_ordered_by_severity() -> None:
    result = evaluate(features(metadata_resolved=False, liquidity_usd=Decimal(100)), MODEL_V1)
    ranks = [meta_for(code).severity for code in result.explanation.reasons]
    order = [Severity.CRITICAL, Severity.CAUTION, Severity.POSITIVE, Severity.INFO]
    positions = [order.index(rank) for rank in ranks]
    assert positions == sorted(positions)


def test_reasons_are_deduplicated() -> None:
    """A code emitted by both a component and the gate appears once."""
    result = evaluate(features(liquidity_usd=Decimal(100)), MODEL_V1)
    assert len(result.reasons) == len(set(result.reasons))


def test_the_coverage_limit_is_always_explained_in_v1() -> None:
    result = evaluate(features(), MODEL_V1)
    assert ReasonCode.CONFIDENCE_LIMITED_BY_COVERAGE in result.reasons


def test_cap_relaxation_is_reported() -> None:
    """Few enough signals that the usual weighting cannot apply."""
    result = evaluate(
        features(
            liquidity_usd=None,
            market_cap=Decimal(500000),
            fully_diluted_valuation=Decimal(550000),
            volume_24h=None,
            buy_count_24h=None,
            sell_count_24h=None,
        ),
        MODEL_V1,
    )
    assert result.scorable is True
    assert ReasonCode.WEIGHT_CAP_RELAXED in result.reasons


# --- Golden corpus ------------------------------------------------------------
#
# Exact expected scores for a fixed set of archetypes. Any change to a weight,
# anchor table, or formula shows its full blast radius here as a diff in the
# pull request - which turns "I tweaked a constant" from an invisible change
# into a reviewable one. Update these deliberately, never to make a test pass.

GOLDEN_CASES: dict[str, object] = {
    "healthy_young_token": features(),
    "excellent_token": _excellent(),
    "textbook_rug": features(
        liquidity_usd=Decimal(50),
        market_cap=Decimal(5000000),
        fully_diluted_valuation=Decimal(5000000),
        window=declining_window(peak=80000, current=50, seconds_ago=900),
    ),
    "dying_pool": features(
        liquidity_usd=Decimal(3000),
        window=declining_window(peak=12000, current=3000, seconds_ago=1800),
    ),
    "dead_pool": features(trading_status="inactive"),
    "no_market_yet": features(
        liquidity_usd=None,
        market_cap=None,
        fully_diluted_valuation=None,
        volume_24h=None,
        buy_count_24h=None,
        sell_count_24h=None,
        window=(),
    ),
    "single_observation": features(window=observations(count=1)),
    "unresolved_metadata": features(metadata_resolved=False),
    "wash_traded_shape": features(buy_count_24h=6, sell_count_24h=0),
    "supply_overhang": features(
        market_cap=Decimal(100000), fully_diluted_valuation=Decimal(5000000)
    ),
    "ancient_token": features(age_minutes=Decimal(20000)),
    "newborn_token": features(age_minutes=Decimal(2)),
}


@pytest.mark.parametrize("name", sorted(GOLDEN_CASES))
def test_golden_corpus_is_stable(name: str, golden_scores: dict[str, str]) -> None:
    result = evaluate(GOLDEN_CASES[name], MODEL_V1)  # type: ignore[arg-type]
    assert f"{result.score}" == golden_scores[name]


def test_the_corpus_is_not_degenerate(golden_scores: dict[str, str]) -> None:
    """Guards the classic failure where careful weighting makes everything ~68."""
    scores = [Decimal(value) for value in golden_scores.values()]
    spread = max(scores) - min(scores)
    assert spread > Decimal(30)

    banded = {int(score // 10) for score in scores}
    assert len(banded) >= 4


@pytest.fixture
def golden_scores() -> dict[str, str]:
    return GOLDEN_SCORES


GOLDEN_SCORES: dict[str, str] = {
    # Past its move but structurally intact.
    "ancient_token": "61.09",
    # Vetoed: pinned to the ceiling regardless of everything else.
    "dead_pool": "35.00",
    # Acute drawdown, penalised but not yet vetoed.
    "dying_pool": "24.03",
    # Deep liquidity, explosive volume, coherent valuation.
    "excellent_token": "93.58",
    "healthy_young_token": "66.62",
    # Too new to say much; the survival curve holds it down.
    "newborn_token": "58.50",
    # Below the scorable floor - declined rather than guessed.
    "no_market_yet": "0.00",
    "single_observation": "66.85",
    "supply_overhang": "64.90",
    # $50 of liquidity behind a $5M valuation, collapsing. The case a linear
    # risk sum scored "moderate".
    "textbook_rug": "13.72",
    "unresolved_metadata": "61.29",
    # A perfect buy ratio on six trades, held down by participation.
    "wash_traded_shape": "59.84",
}
