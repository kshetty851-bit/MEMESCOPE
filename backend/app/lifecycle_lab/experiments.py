"""Meme Lifecycle Lab — experiment registry primitives.

* ``chronological_split`` — train / validation / test as three contiguous,
  end-exclusive time ranges. Never shuffled: a shuffled split on a time series
  leaks the future into training.
* ``ExperimentSpec`` — what was tested, on which data, under which config,
  and its ``spec_hash``. Any change to a spec is a new spec.
* ``sample_label`` — sample-size language. A result on 30 trades is not
  evidence of anything, and the label says so on every surface.
* ``multiple_testing_note`` — every additional spec tried on the same data is
  another draw; past a threshold the note says so and gives a Bonferroni alpha.

Pure: no I/O, no clock, no randomness. ``created_at`` is a parameter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from app.lifecycle_lab.config import LabConfig
from app.lifecycle_lab.domain import (
    Arm,
    ResearchMode,
    SplitSegment,
    _canonical,
    spec_hash,
)
from app.lifecycle_lab.strategy import strategy_spec

DEFAULT_FRACTIONS: tuple[float, float, float] = (0.7, 0.15, 0.15)

#: Below this much forward data a split is not meaningful. Four weeks: enough
#: for the test segment (15%) to span about four days, i.e. more than one
#: weekly cycle of attention once train and validation are carved out.
MIN_FORWARD_SPAN = timedelta(days=28)

#: Sample-size ladder. Mirrors ``app.lab.leaderboard.CONFIDENCE_STEPS`` and
#: ``confidence()`` exactly — same floors, same labels — so a Lab result and an
#: Arena result with the same trade count read the same. Restated rather than
#: imported because ``app.lab.leaderboard`` imports SQLAlchemy and the ORM,
#: which a pure engine may not.
CONFIDENCE_STEPS: tuple[tuple[int, str], ...] = (
    (500, "SUBSTANTIAL"),
    (200, "INTERMEDIATE"),
    (100, "PRELIMINARY"),
    (50, "EARLY"),
    (25, "EXTREMELY_LOW_CONFIDENCE"),
)
INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
#: The ladder's first rung: fewer closed trades than this and no split is
#: meaningful whatever the time span.
MIN_TRADES = CONFIDENCE_STEPS[-1][0]

#: The pre-registered arm set — baseline + four controls — is evaluated
#: together by design. Testing more specs than that against the same data is
#: where selection bias starts, so the note appears above it.
MULTIPLE_TESTING_THRESHOLD = 5
DEFAULT_ALPHA = Decimal("0.05")

SPLIT_NOTE_INSUFFICIENT_FORWARD = "insufficient forward data"
SPLIT_NOTE_INSUFFICIENT_TRADES = "insufficient trades"


def sample_label(n_trades: int) -> str:
    for floor, label in CONFIDENCE_STEPS:
        if n_trades >= floor:
            return label
    return INSUFFICIENT_SAMPLE


def multiple_testing_note(n_tested: int, *, alpha: Decimal = DEFAULT_ALPHA) -> str | None:
    """``None`` at or below the threshold; a warning with the Bonferroni alpha
    above it. Bonferroni is conservative, which is the right direction for a
    lab whose failure mode is believing a lucky spec."""
    if n_tested <= MULTIPLE_TESTING_THRESHOLD:
        return None
    adjusted = (alpha / Decimal(n_tested)).quantize(Decimal("0.000001"))
    return (
        f"POSSIBLE MULTIPLE-TESTING / SELECTION BIAS: {n_tested} specs tested on "
        f"this data; Bonferroni-adjusted alpha {adjusted} ({alpha} / {n_tested})."
    )


def chronological_split(
    start: datetime,
    end: datetime,
    fractions: tuple[float, float, float] = DEFAULT_FRACTIONS,
) -> dict[SplitSegment, tuple[datetime, datetime]]:
    """Three contiguous end-exclusive ranges covering ``[start, end)``.

    Boundaries are computed in whole microseconds from exact decimal fractions,
    so the same inputs always give the same boundaries and the segments meet
    exactly (``train.end == validation.start``).
    """
    if end <= start:
        raise ValueError("end must be after start")
    if len(fractions) != 3 or any(f <= 0 for f in fractions):
        raise ValueError("fractions must be three positive numbers")
    exact = [Decimal(str(f)) for f in fractions]
    if sum(exact) != Decimal(1):
        raise ValueError("fractions must sum to 1")
    span = end - start
    total_us = (span.days * 86_400 + span.seconds) * 1_000_000 + span.microseconds
    cut1 = start + timedelta(microseconds=int(Decimal(total_us) * exact[0]))
    cut2 = start + timedelta(microseconds=int(Decimal(total_us) * (exact[0] + exact[1])))
    return {
        SplitSegment.TRAIN: (start, cut1),
        SplitSegment.VALIDATION: (cut1, cut2),
        SplitSegment.TEST: (cut2, end),
    }


@dataclass(frozen=True, slots=True)
class ExperimentSpec:
    experiment_key: str
    hypothesis: str
    created_at: datetime
    data_cutoff: datetime
    train_start: datetime
    train_end: datetime
    validation_start: datetime
    validation_end: datetime
    test_start: datetime
    test_end: datetime
    strategy_spec: dict[str, Any]
    config_spec: dict[str, Any]
    mode: ResearchMode
    arm: Arm
    split_meaningful: bool
    split_note: str | None
    spec_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_key": self.experiment_key,
            "hypothesis": self.hypothesis,
            "created_at": self.created_at.isoformat(),
            "data_cutoff": self.data_cutoff.isoformat(),
            "train_start": self.train_start.isoformat(),
            "train_end": self.train_end.isoformat(),
            "validation_start": self.validation_start.isoformat(),
            "validation_end": self.validation_end.isoformat(),
            "test_start": self.test_start.isoformat(),
            "test_end": self.test_end.isoformat(),
            "strategy_spec": _jsonable(self.strategy_spec),
            "config_spec": _jsonable(self.config_spec),
            "mode": self.mode.value,
            "arm": self.arm.value,
            "split_meaningful": self.split_meaningful,
            "split_note": self.split_note,
            "spec_hash": self.spec_hash,
        }


def _jsonable(value: Any) -> Any:
    # The same canonical form spec_hash uses, so the stored spec and the
    # hashed spec cannot disagree.
    return _canonical(value)


def build_experiment(
    *,
    experiment_key: str,
    hypothesis: str,
    created_at: datetime,
    start: datetime,
    end: datetime,
    cfg: LabConfig,
    mode: ResearchMode,
    arm: Arm,
    forward_start: datetime | None,
    n_trades: int | None = None,
    fractions: tuple[float, float, float] = DEFAULT_FRACTIONS,
) -> ExperimentSpec:
    """Register a spec. ``data_cutoff`` is ``end``: nothing at or after it was
    available to the experiment.

    ``split_meaningful`` is False with a note when the forward span inside
    ``[start, end)`` is under ``MIN_FORWARD_SPAN`` (no ``forward_start`` means
    no forward data at all), or when a known ``n_trades`` is under
    ``MIN_TRADES``. The split boundaries are still recorded — they are what
    the experiment *would* use — but nothing may be read as out-of-sample.

    ``spec_hash`` covers everything that changes results and excludes
    ``experiment_key`` and ``created_at``, so the same spec registered twice
    hashes the same — which is how repeated tries are counted.
    """
    splits = chronological_split(start, end, fractions)
    if forward_start is None:
        forward_span = timedelta(0)
    else:
        forward_span = max(timedelta(0), end - max(start, forward_start))
    note: str | None = None
    if forward_span < MIN_FORWARD_SPAN:
        note = SPLIT_NOTE_INSUFFICIENT_FORWARD
    elif n_trades is not None and n_trades < MIN_TRADES:
        note = SPLIT_NOTE_INSUFFICIENT_TRADES
    s_spec = strategy_spec(arm, cfg.baseline)
    c_spec = cfg.as_spec()
    hashed = {
        "hypothesis": hypothesis,
        "data_cutoff": end,
        "splits": {seg.value: list(rng) for seg, rng in splits.items()},
        "strategy_spec": s_spec,
        "config_spec": c_spec,
        "mode": mode,
        "arm": arm,
    }
    train, validation, test = (
        splits[SplitSegment.TRAIN],
        splits[SplitSegment.VALIDATION],
        splits[SplitSegment.TEST],
    )
    return ExperimentSpec(
        experiment_key=experiment_key,
        hypothesis=hypothesis,
        created_at=created_at,
        data_cutoff=end,
        train_start=train[0],
        train_end=train[1],
        validation_start=validation[0],
        validation_end=validation[1],
        test_start=test[0],
        test_end=test[1],
        strategy_spec=s_spec,
        config_spec=c_spec,
        mode=mode,
        arm=arm,
        split_meaningful=note is None,
        split_note=note,
        spec_hash=spec_hash(hashed),
    )
