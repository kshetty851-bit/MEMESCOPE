"""Materiality tests.

The rule that keeps the Observatory Log a record of events rather than a log of
every 30-second re-evaluation. Pure, so these need no database.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.models.score import ScoreGrade, ScoreTrigger
from app.services.scoring.materiality import (
    MaterialityPolicy,
    PreviousScore,
    decide,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
POLICY = MaterialityPolicy(
    min_delta=Decimal("2.0"),
    grade_deadband=Decimal("0.5"),
    min_interval_seconds=300,
)


def _previous(**overrides: object) -> PreviousScore:
    values: dict[str, object] = {
        "score": Decimal("60.00"),
        "grade": ScoreGrade.WATCH,
        "is_elite": False,
        "has_veto": False,
        "evaluated_at": NOW - timedelta(seconds=30),
    }
    values.update(overrides)
    return PreviousScore(**values)  # type: ignore[arg-type]


def _decide(**overrides: object):
    values: dict[str, object] = {
        "score": Decimal("60.00"),
        "grade": ScoreGrade.WATCH,
        "is_elite": False,
        "has_veto": False,
        "evaluated_at": NOW,
        "previous": _previous(),
        "policy": POLICY,
    }
    values.update(overrides)
    return decide(**values)  # type: ignore[arg-type]


def test_the_first_evaluation_always_writes() -> None:
    """Guarantees the per-token detail lookup always resolves."""
    decision = _decide(previous=None)
    assert decision.write_history is True
    assert decision.trigger is ScoreTrigger.FIRST
    assert decision.delta is None


def test_an_unchanged_score_writes_nothing() -> None:
    assert _decide().write_history is False


def test_a_large_move_writes() -> None:
    decision = _decide(score=Decimal("63.00"))
    assert decision.write_history is True
    assert decision.trigger is ScoreTrigger.DELTA
    assert decision.delta == Decimal("3.00")


def test_a_small_move_does_not() -> None:
    assert _decide(score=Decimal("61.00")).write_history is False


def test_a_veto_engaging_always_writes() -> None:
    """A rug being caught must never be suppressed by a small delta."""
    decision = _decide(has_veto=True, score=Decimal("60.10"))
    assert decision.write_history is True
    assert decision.trigger is ScoreTrigger.VETO_CHANGE


def test_a_veto_clearing_writes() -> None:
    decision = _decide(previous=_previous(has_veto=True), has_veto=False)
    assert decision.trigger is ScoreTrigger.VETO_CHANGE


def test_elite_toggling_writes() -> None:
    decision = _decide(is_elite=True, score=Decimal("60.10"))
    assert decision.write_history is True
    assert decision.trigger is ScoreTrigger.ELITE_CHANGE


def test_a_grade_change_writes_when_the_move_is_real() -> None:
    """A move too small for the delta trigger, but big enough to mean the band.

    1.50 sits between the deadband (0.5) and the delta threshold (2.0), which is
    the only window where the grade trigger is the one that fires.
    """
    decision = _decide(
        previous=_previous(score=Decimal("64.00"), grade=ScoreGrade.WATCH),
        score=Decimal("65.50"),
        grade=ScoreGrade.STRONG,
    )
    assert decision.write_history is True
    assert decision.trigger is ScoreTrigger.GRADE_CHANGE


def test_a_large_move_is_attributed_to_the_delta_not_the_grade() -> None:
    """Precedence: report the magnitude, not the band it happened to cross."""
    decision = _decide(score=Decimal("64.90"), grade=ScoreGrade.STRONG)
    assert decision.trigger is ScoreTrigger.DELTA


def test_band_edge_oscillation_is_suppressed() -> None:
    """The deadband. Without it a score wobbling across 65.00 writes forever."""
    decision = _decide(
        previous=_previous(score=Decimal("64.99"), grade=ScoreGrade.WATCH),
        score=Decimal("65.00"),
        grade=ScoreGrade.STRONG,
    )
    assert decision.write_history is False


def test_the_heartbeat_writes_a_flat_token() -> None:
    """So history reads as a time series, not just a list of surprises."""
    decision = _decide(previous=_previous(evaluated_at=NOW - timedelta(seconds=301)))
    assert decision.write_history is True
    assert decision.trigger is ScoreTrigger.HEARTBEAT


def test_the_heartbeat_does_not_fire_early() -> None:
    decision = _decide(previous=_previous(evaluated_at=NOW - timedelta(seconds=299)))
    assert decision.write_history is False


def test_the_veto_outranks_a_coincident_delta() -> None:
    """Attribution matters: the log should say why, not what happened alongside."""
    decision = _decide(has_veto=True, score=Decimal("20.00"))
    assert decision.trigger is ScoreTrigger.VETO_CHANGE


def test_delta_is_signed() -> None:
    assert _decide(score=Decimal("50.00")).delta == Decimal("-10.00")
