"""Evidence and grading tests.

Evidence is the axis that keeps "we cannot see most of this token" from being
rendered as a confident number. The multiplicative form is the load-bearing
part: any factor collapsing must collapse the result, because an additive form
would let a strong factor mask an absent one.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.score import ScoreGrade
from app.services.scoring.components.base import ComponentId, ComponentResult
from app.services.scoring.evidence import assess, coverage_of, depth_of
from app.services.scoring.explain import AgentId, ReasonCode
from app.services.scoring.grading import (
    EliteGate,
    GradeBands,
    elite_status,
    grade_for,
    qualifies_for_elite,
)
from app.services.scoring.models.v1 import MODEL_V1
from app.services.scoring.normalisers import HUNDRED, ONE, ZERO

pytestmark = pytest.mark.unit

DECLARED = MODEL_V1.declared_weights


def _result(component_id: ComponentId, *, available: bool) -> ComponentResult:
    return ComponentResult(
        id=component_id,
        agent=AgentId.ORACLE,
        available=available,
        score=Decimal(50) if available else None,
    )


def _v1_available() -> list[ComponentResult]:
    """The five components v1 can actually evaluate."""
    available = {
        ComponentId.LIQUIDITY_DEPTH,
        ComponentId.MOMENTUM,
        ComponentId.TRADE_FLOW,
        ComponentId.VALUATION_STRUCTURE,
        ComponentId.SURVIVAL_AGE,
    }
    return [
        _result(component_id, available=component_id in available) for component_id in DECLARED
    ]


# --- Coverage -----------------------------------------------------------------


def test_v1_coverage_is_capped_at_sixty_five_percent() -> None:
    """The arithmetic that makes v1's incompleteness visible in every score."""
    assert coverage_of(_v1_available(), DECLARED) == Decimal("0.65")


def test_full_coverage_when_everything_is_available() -> None:
    everything = [_result(component_id, available=True) for component_id in DECLARED]
    assert coverage_of(everything, DECLARED) == ONE


def test_zero_coverage_when_nothing_is_available() -> None:
    nothing = [_result(component_id, available=False) for component_id in DECLARED]
    assert coverage_of(nothing, DECLARED) == ZERO


def test_coverage_of_an_empty_model_is_zero() -> None:
    assert coverage_of([], {}) == ZERO


# --- Depth --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("observations", "expected"),
    [(0, "0"), (1, "0.3333333333333333333333333333"), (3, "1"), (12, "1")],
)
def test_depth_saturates_at_the_requirement(observations: int, expected: str) -> None:
    assert depth_of(observations, 3) == Decimal(expected)


def test_depth_of_a_negative_count_is_zero() -> None:
    assert depth_of(-5, 3) == ZERO


def test_depth_without_a_requirement_is_full() -> None:
    assert depth_of(0, 0) == ONE


# --- Evidence -----------------------------------------------------------------


def test_evidence_collapses_when_either_factor_collapses() -> None:
    """Multiplicative, not additive. This is the whole reason for the form."""
    no_observations = assess(
        _v1_available(), DECLARED, observations=0, required_observations=3
    )
    no_coverage = assess(
        [_result(component_id, available=False) for component_id in DECLARED],
        DECLARED,
        observations=12,
        required_observations=3,
    )
    assert no_observations.evidence == ZERO
    assert no_coverage.evidence == ZERO


def test_v1_evidence_tops_out_at_sixty_five() -> None:
    """Which is why Elite (70) is unreachable until Day 6."""
    assessment = assess(_v1_available(), DECLARED, observations=12, required_observations=3)
    assert assessment.evidence == Decimal(65)
    assert assessment.coverage_score == Decimal(65)


def test_full_evidence_is_reachable_when_every_signal_exists() -> None:
    everything = [_result(component_id, available=True) for component_id in DECLARED]
    assessment = assess(everything, DECLARED, observations=3, required_observations=3)
    assert assessment.evidence == HUNDRED


def test_partial_history_discounts_gently() -> None:
    """A short history is a weaker objection than a missing signal."""
    shallow = assess(_v1_available(), DECLARED, observations=1, required_observations=3)
    deep = assess(_v1_available(), DECLARED, observations=3, required_observations=3)
    assert ZERO < shallow.evidence < deep.evidence


def test_the_limiting_factor_is_named() -> None:
    coverage_limited = assess(
        _v1_available(), DECLARED, observations=12, required_observations=3
    )
    assert coverage_limited.limiting_reason is ReasonCode.CONFIDENCE_LIMITED_BY_COVERAGE

    everything = [_result(component_id, available=True) for component_id in DECLARED]
    history_limited = assess(everything, DECLARED, observations=1, required_observations=3)
    assert history_limited.limiting_reason is ReasonCode.CONFIDENCE_LIMITED_BY_HISTORY


def test_no_limiting_factor_when_nothing_limits() -> None:
    everything = [_result(component_id, available=True) for component_id in DECLARED]
    assessment = assess(everything, DECLARED, observations=3, required_observations=3)
    assert assessment.limiting_reason is None


def test_evidence_stays_within_range() -> None:
    for observations in range(0, 10):
        assessment = assess(
            _v1_available(), DECLARED, observations=observations, required_observations=3
        )
        assert ZERO <= assessment.evidence <= HUNDRED


# --- Grade bands --------------------------------------------------------------


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0, ScoreGrade.CRITICAL),
        (29, ScoreGrade.CRITICAL),
        (30, ScoreGrade.WEAK),
        (49, ScoreGrade.WEAK),
        (50, ScoreGrade.WATCH),
        (64, ScoreGrade.WATCH),
        (65, ScoreGrade.STRONG),
        (79, ScoreGrade.STRONG),
        (80, ScoreGrade.HIGH_CONVICTION),
        (100, ScoreGrade.HIGH_CONVICTION),
    ],
)
def test_grade_boundaries(score: int, expected: ScoreGrade) -> None:
    assert grade_for(Decimal(score), GradeBands()) is expected


def test_grade_bands_are_exhaustive() -> None:
    """Every score in range must land in exactly one band."""
    seen = {grade_for(Decimal(step), GradeBands()) for step in range(0, 101)}
    assert seen == set(ScoreGrade)


def test_grade_bands_must_ascend() -> None:
    with pytest.raises(ValueError, match="ascend"):
        GradeBands(weak_from=Decimal(60), watch_from=Decimal(50))


def test_grade_bands_must_be_non_negative() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        GradeBands(weak_from=Decimal(-1))


# --- Elite gate ---------------------------------------------------------------


def _elite_kwargs(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "score": Decimal(90),
        "evidence": Decimal(80),
        "risk_penalty": Decimal("0.1"),
        "liquidity_usd": Decimal(50000),
        "vetoed": False,
        "gate": EliteGate(),
    }
    values.update(overrides)
    return values


def test_a_strong_well_evidenced_token_qualifies() -> None:
    assert qualifies_for_elite(**_elite_kwargs())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "override",
    [
        {"score": Decimal(84)},
        {"evidence": Decimal(69)},
        {"risk_penalty": Decimal("0.21")},
        {"liquidity_usd": Decimal(24999)},
        {"liquidity_usd": None},
        {"vetoed": True},
    ],
    ids=["score", "evidence", "risk", "liquidity", "no-liquidity", "vetoed"],
)
def test_every_criterion_is_load_bearing(override: dict[str, object]) -> None:
    assert not qualifies_for_elite(**_elite_kwargs(**override))  # type: ignore[arg-type]


def test_v1_evidence_ceiling_makes_elite_unreachable() -> None:
    """65 is the most v1 can evidence; the gate needs 70. Gold stays dark."""
    assert not qualifies_for_elite(**_elite_kwargs(evidence=Decimal(65)))  # type: ignore[arg-type]


def test_elite_requires_a_sustained_streak() -> None:
    gate = EliteGate()
    for prior in range(gate.sustain_evaluations - 1):
        is_elite, streak = elite_status(qualifies=True, prior_streak=prior, gate=gate)
        assert is_elite is False
        assert streak == prior + 1

    is_elite, streak = elite_status(
        qualifies=True, prior_streak=gate.sustain_evaluations - 1, gate=gate
    )
    assert is_elite is True
    assert streak == gate.sustain_evaluations


def test_a_failed_evaluation_resets_the_streak() -> None:
    is_elite, streak = elite_status(qualifies=False, prior_streak=9, gate=EliteGate())
    assert is_elite is False
    assert streak == 0
