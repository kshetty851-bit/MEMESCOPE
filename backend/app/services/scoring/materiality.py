"""When a score change is worth recording.

`token_scores` is upserted on every evaluation. History is not: a 30-second
refresh tier would otherwise write ~2,880 near-identical rows per token per day,
and since the Observatory Log renders from history, the product's mission log
would fill with entries reporting that nothing happened.

Pure, like the engine. The comparison is always against the **most recent
history row** rather than a mutable column on `token_scores`, because three
writers touch that table concurrently and a read-modify-write counter is exactly
the hazard the schema was designed to avoid.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.models.score import ScoreGrade, ScoreTrigger


@dataclass(frozen=True, slots=True)
class PreviousScore:
    """The stored history row a new evaluation is compared against.

    A value object rather than the ORM row: materiality is a pure rule, and
    taking a `TokenScoreHistory` here would drag SQLAlchemy into a module that
    has no business knowing the database exists.
    """

    score: Decimal
    grade: ScoreGrade
    is_elite: bool
    has_veto: bool
    evaluated_at: datetime


@dataclass(frozen=True, slots=True)
class MaterialityPolicy:
    min_delta: Decimal
    grade_deadband: Decimal
    min_interval_seconds: int


@dataclass(frozen=True, slots=True)
class MaterialityDecision:
    write_history: bool
    trigger: ScoreTrigger
    delta: Decimal | None


def decide(
    *,
    score: Decimal,
    grade: ScoreGrade,
    is_elite: bool,
    has_veto: bool,
    evaluated_at: datetime,
    previous: PreviousScore | None,
    policy: MaterialityPolicy,
) -> MaterialityDecision:
    """Decide whether this evaluation earns a history row.

    Order matters: the first matching trigger is the one recorded, and they are
    checked most-significant first so that a rug being caught is attributed to
    the veto rather than to whatever delta happened to accompany it.
    """
    if previous is None:
        # Always written. Guarantees the per-token detail lookup always resolves,
        # so the API never has to handle "scored, but no breakdown exists".
        return MaterialityDecision(True, ScoreTrigger.FIRST, None)

    delta = score - previous.score

    if has_veto != previous.has_veto:
        return MaterialityDecision(True, ScoreTrigger.VETO_CHANGE, delta)

    if is_elite != previous.is_elite:
        return MaterialityDecision(True, ScoreTrigger.ELITE_CHANGE, delta)

    if abs(delta) >= policy.min_delta:
        return MaterialityDecision(True, ScoreTrigger.DELTA, delta)

    # A grade change alone is not enough. Without the deadband, a score
    # oscillating either side of a band edge by hundredths would write a row
    # every evaluation while reporting a change nobody would call one.
    if grade is not previous.grade and abs(delta) >= policy.grade_deadband:
        return MaterialityDecision(True, ScoreTrigger.GRADE_CHANGE, delta)

    elapsed = (evaluated_at - previous.evaluated_at).total_seconds()
    if elapsed >= policy.min_interval_seconds:
        # Heartbeat: a flat token still leaves a sampled trace, so history can
        # be read as a time series rather than a list of surprises.
        return MaterialityDecision(True, ScoreTrigger.HEARTBEAT, delta)

    return MaterialityDecision(False, ScoreTrigger.DELTA, delta)
