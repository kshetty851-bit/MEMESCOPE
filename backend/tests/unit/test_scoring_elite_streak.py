"""The Elite streak, replayed from stored history.

Pure enough to test without a database even though it lives beside the service:
it reads rows and counts, and that counting is what keeps certification
reproducible under concurrent writers instead of depending on a mutable column.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.models.score import ScoreGrade, TokenScoreHistory
from app.services.scoring.grading import EliteGate
from app.services.scoring.service import _elite_streak_from

pytestmark = pytest.mark.unit

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
GATE = EliteGate()


def _row(*, index: int = 0, qualifying: bool = True, **overrides: Any) -> TokenScoreHistory:
    """A history row, built in memory - never added to a session."""
    values: dict[str, Any] = {
        "mint_address": "MintStreak",
        "model_version": "v1",
        "score": Decimal("90.00") if qualifying else Decimal("40.00"),
        "evidence": Decimal("80.00") if qualifying else Decimal("50.00"),
        "coverage": Decimal("100.00"),
        "market_risk": Decimal("5.00"),
        "opportunity_raw": Decimal("90.00"),
        "observations": 12,
        "grade": ScoreGrade.HIGH_CONVICTION,
        "is_elite": False,
        "has_veto": False,
        "trigger": "delta",
        "evaluated_at": NOW - timedelta(minutes=index),
    }
    values.update(overrides)
    return TokenScoreHistory(**values)


def test_no_history_means_no_streak() -> None:
    assert _elite_streak_from([], GATE) == 0


def test_consecutive_qualifying_rows_accumulate() -> None:
    rows = [_row(index=index) for index in range(3)]
    assert _elite_streak_from(rows, GATE) == 3


def test_the_streak_stops_at_the_first_failure() -> None:
    """Newest first, so a recent lapse resets regardless of older strength."""
    rows = [_row(index=0), _row(index=1, qualifying=False), _row(index=2)]
    assert _elite_streak_from(rows, GATE) == 1


def test_a_recent_lapse_zeroes_the_streak() -> None:
    rows = [_row(index=0, qualifying=False), _row(index=1), _row(index=2)]
    assert _elite_streak_from(rows, GATE) == 0


def test_a_veto_breaks_the_streak_whatever_the_score() -> None:
    """Gold must never be granted to a token the risk gate has vetoed."""
    rows = [_row(index=0, has_veto=True)]
    assert _elite_streak_from(rows, GATE) == 0


def test_low_evidence_breaks_the_streak() -> None:
    """Which is why v1 - capped at 65 evidence - can never accumulate one."""
    rows = [_row(index=index, evidence=Decimal("65.00")) for index in range(3)]
    assert _elite_streak_from(rows, GATE) == 0


def test_a_low_score_breaks_the_streak() -> None:
    rows = [_row(index=0, score=Decimal("84.99"))]
    assert _elite_streak_from(rows, GATE) == 0


def test_excess_risk_breaks_the_streak() -> None:
    """`max_risk_penalty` is a fraction; history stores risk on the 0-100 scale."""
    rows = [_row(index=0, market_risk=Decimal("25.00"))]
    assert _elite_streak_from(rows, GATE) == 0

    borderline = [_row(index=0, market_risk=Decimal("20.00"))]
    assert _elite_streak_from(borderline, GATE) == 1
