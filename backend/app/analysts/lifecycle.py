"""Lifecycle Intelligence — where a project sits on its own arc.

Seven mission states, assigned by ordered rules. This is the backend home of
the classification Phase 13 prototyped in the frontend: moving it here makes it
one authority rather than two, and lets the dossier, the queue and any future
alert agree by construction instead of by coincidence.

## What it deliberately does not answer

Not "is this good" — the scoring engine owns that and its grade is the answer.
Lifecycle asks a different question, and the two readings are orthogonal: a
project can be ASCENT and still score Speculative, because climbing on thin
evidence is a real and common situation. If this analyst ever started implying
quality, it would be a second opinion on the engine's question and would have
to go.

## Ordering is the specification

Rules are evaluated in sequence and the first match wins. Two orderings carry
weight:

  * **LOST_CONTACT outranks everything except RECON.** A vetoed or collapsing
    project must not read as ASCENT because its multiple happens to sit above
    1.0.
  * **RECON outranks LOST_CONTACT.** Below the observation floor there is no
    basis for either verdict, and declaring a project lost on four data points
    invents certainty the platform does not have.
"""

from __future__ import annotations

import enum
from decimal import Decimal

from app.analysts.base import AnalystId, AnalystMeta, Evidence, Reading, RiskWarning, Severity


class MissionState(enum.StrEnum):
    RECON = "recon"
    LAUNCH_WINDOW = "launch_window"
    ASCENT = "ascent"
    ORBIT = "orbit"
    HOLDING_PATTERN = "holding_pattern"
    RE_ENTRY = "re_entry"
    LOST_CONTACT = "lost_contact"


META = AnalystMeta(
    id=AnalystId.LIFECYCLE,
    name="Lifecycle Intelligence",
    question="Where is this project on its own journey since detection?",
    operational=True,
    evidence_fields=("current_multiple", "peak_multiple", "days_since_detection"),
)

MIN_OBSERVATIONS = 12
LAUNCH_WINDOW_DAYS = Decimal(1)
NEAR_PEAK = Decimal("0.9")
DEEP_DRAWDOWN = Decimal("0.5")
FLAT_BAND = Decimal("0.97")

STATE_MEANING: dict[MissionState, str] = {
    MissionState.RECON: (
        "Too little observed history for LETZMOON to have a view. It is being "
        "watched, not assessed."
    ),
    MissionState.LAUNCH_WINDOW: (
        "Detected within the last day and still close to the price it was found "
        "at. Everything about it is provisional."
    ),
    MissionState.ASCENT: (
        "Above its detection price and at or near its highest observed point. It "
        "has not given the move back."
    ),
    MissionState.ORBIT: (
        "Still above its detection price but off its high. It held some of the "
        "move rather than round-tripping."
    ),
    MissionState.HOLDING_PATTERN: (
        "Close to where it was detected, with no material move in either direction since."
    ),
    MissionState.RE_ENTRY: (
        "Below its detection price, having given back most of what it reached."
    ),
    MissionState.LOST_CONTACT: (
        "Down heavily from its own peak, vetoed by the risk gate, or flagged at "
        "the highest Exit Watch severity."
    ),
}

STATE_RULE: dict[MissionState, str] = {
    MissionState.RECON: f"Fewer than {MIN_OBSERVATIONS} observations.",
    MissionState.LAUNCH_WINDOW: f"Detected less than {LAUNCH_WINDOW_DAYS} day ago.",
    MissionState.ASCENT: (
        f"At or above detection price, holding at least {NEAR_PEAK:%} of its peak."
    ),
    MissionState.ORBIT: "At or above detection price, below that share of its peak.",
    MissionState.HOLDING_PATTERN: f"Within {1 - FLAT_BAND:.0%} of the detection price.",
    MissionState.RE_ENTRY: (
        f"Below detection price, holding more than {DEEP_DRAWDOWN:%} of its peak."
    ),
    MissionState.LOST_CONTACT: (
        f"Vetoed, at elevated Exit Watch, or holding less than {DEEP_DRAWDOWN:%} of its peak."
    ),
}


def classify(
    *,
    current_multiple: Decimal | None,
    peak_multiple: Decimal | None,
    days_since_detection: Decimal,
    exit_severity: str | None,
    has_veto: bool,
    observations: int,
) -> MissionState:
    """Assign a mission state. Pure, total and deterministic."""
    if observations < MIN_OBSERVATIONS or current_multiple is None:
        return MissionState.RECON

    if has_veto or exit_severity == "elevated":
        return MissionState.LOST_CONTACT

    peak = peak_multiple if peak_multiple is not None else current_multiple
    held = current_multiple / peak if peak > 0 else Decimal(1)

    if held < DEEP_DRAWDOWN:
        return MissionState.LOST_CONTACT

    if days_since_detection < LAUNCH_WINDOW_DAYS:
        return MissionState.LAUNCH_WINDOW

    if current_multiple >= 1:
        return MissionState.ASCENT if held >= NEAR_PEAK else MissionState.ORBIT

    if current_multiple >= FLAT_BAND:
        return MissionState.HOLDING_PATTERN

    return MissionState.RE_ENTRY


def analyse(
    *,
    current_multiple: Decimal | None,
    peak_multiple: Decimal | None,
    days_since_detection: Decimal,
    exit_severity: str | None,
    has_veto: bool,
    observations: int,
) -> Reading:
    state = classify(
        current_multiple=current_multiple,
        peak_multiple=peak_multiple,
        days_since_detection=days_since_detection,
        exit_severity=exit_severity,
        has_veto=has_veto,
        observations=observations,
    )

    evidence: list[Evidence] = [
        Evidence("Mission status", state.value.replace("_", " ").title()),
        Evidence("Rule applied", STATE_RULE[state]),
    ]
    warnings: list[RiskWarning] = []

    if current_multiple is not None:
        evidence.append(Evidence("Return since detection", f"{current_multiple:.2f}x"))
    if peak_multiple is not None and current_multiple is not None and peak_multiple > 0:
        off_peak = (1 - current_multiple / peak_multiple) * 100
        evidence.append(Evidence("Peak since detection", f"{peak_multiple:.2f}x"))
        if off_peak > 0:
            evidence.append(Evidence("Below its peak", f"{off_peak:.0f}%"))
        if off_peak >= 30:
            warnings.append(
                RiskWarning(
                    code="LIFECYCLE_OFF_PEAK",
                    severity=Severity.CAUTION,
                    message=(
                        f"This is {off_peak:.0f}% below its own peak. A project "
                        "climbing and one that round-tripped can show the same "
                        "current figure."
                    ),
                )
            )

    if state is MissionState.RECON:
        warnings.append(
            RiskWarning(
                code="LIFECYCLE_INSUFFICIENT_HISTORY",
                severity=Severity.INFO,
                message=(
                    f"Fewer than {MIN_OBSERVATIONS} observations, so no lifecycle "
                    "verdict is offered — good or bad."
                ),
            )
        )

    # Lifecycle is arithmetic on stored figures, so confidence tracks how much
    # was stored rather than how sure the analyst feels.
    confidence = (
        Decimal(20)
        if state is MissionState.RECON
        else min(Decimal(90), Decimal(40) + Decimal(observations))
    )
    # The state is a classification, not a quality score. It is reported through
    # evidence; the numeric score is the share of its peak the project holds,
    # which is the one continuous quantity this analyst actually measures.
    score: Decimal | None = None
    if current_multiple is not None and peak_multiple and peak_multiple > 0:
        score = min(Decimal(100), current_multiple / peak_multiple * 100)

    return Reading(
        analyst=AnalystId.LIFECYCLE,
        score=score,
        confidence=confidence if score is not None else None,
        reason=STATE_MEANING[state],
        evidence=tuple(evidence),
        warnings=tuple(warnings),
    )
