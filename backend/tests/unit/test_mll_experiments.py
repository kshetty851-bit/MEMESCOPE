"""Meme Lifecycle Lab — experiment registry primitives.

A time-series split must be chronological and contiguous, or the future
leaks into training. A spec's hash must be stable, or repeated tries cannot be
counted — and counting them is how selection bias gets flagged.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.lifecycle_lab.config import BaselineStrategyConfig, LabConfig
from app.lifecycle_lab.domain import Arm, ResearchMode, SplitSegment
from app.lifecycle_lab.experiments import (
    MULTIPLE_TESTING_THRESHOLD,
    SPLIT_NOTE_INSUFFICIENT_FORWARD,
    SPLIT_NOTE_INSUFFICIENT_TRADES,
    build_experiment,
    chronological_split,
    multiple_testing_note,
    sample_label,
)

pytestmark = pytest.mark.unit

START = datetime(2026, 9, 1, tzinfo=UTC)
END = START + timedelta(days=100)


def test_split_is_chronological_contiguous_and_70_15_15() -> None:
    s = chronological_split(START, END)
    train, val, test = s[SplitSegment.TRAIN], s[SplitSegment.VALIDATION], s[SplitSegment.TEST]
    assert train[0] == START and test[1] == END
    assert train[1] == val[0] and val[1] == test[0]  # contiguous, no gap, no overlap
    assert train[0] < train[1] < val[1] < test[1]  # strictly ordered, never shuffled
    assert train[1] - train[0] == timedelta(days=70)
    assert val[1] - val[0] == timedelta(days=15)
    assert test[1] - test[0] == timedelta(days=15)


def test_split_is_deterministic_on_awkward_spans() -> None:
    end = START + timedelta(days=7, seconds=13, microseconds=7)
    assert chronological_split(START, end) == chronological_split(START, end)
    s = chronological_split(START, end)
    assert s[SplitSegment.TRAIN][1] == s[SplitSegment.VALIDATION][0]


@pytest.mark.parametrize("fractions", [(0.5, 0.5, 0.5), (0.7, 0.3, 0.0), (1.0, 0.0, 0.0)])
def test_split_rejects_bad_fractions(fractions: tuple[float, float, float]) -> None:
    with pytest.raises(ValueError):
        chronological_split(START, END, fractions)


def test_split_rejects_empty_window() -> None:
    with pytest.raises(ValueError):
        chronological_split(END, START)


def _spec(**kw: object):  # type: ignore[no-untyped-def]
    args: dict[str, object] = {
        "experiment_key": "exp-1",
        "hypothesis": "h",
        "created_at": START,
        "start": START,
        "end": END,
        "cfg": LabConfig(),
        "mode": ResearchMode.AUTHORITATIVE,
        "arm": Arm.BASELINE,
        "forward_start": START,
    }
    args.update(kw)
    return build_experiment(**args)  # type: ignore[arg-type]


def test_spec_hash_is_stable_and_ignores_registration_identity() -> None:
    """The same spec registered twice hashes the same — so repeats are counted."""
    a = _spec()
    b = _spec(experiment_key="exp-2", created_at=START + timedelta(days=3))
    assert a.spec_hash == b.spec_hash
    assert len(a.spec_hash) == 64


def test_spec_hash_changes_with_anything_that_changes_results() -> None:
    base = _spec().spec_hash
    cfg = LabConfig(baseline=replace(BaselineStrategyConfig(), min_acceleration=Decimal(2)))
    assert _spec(cfg=cfg).spec_hash != base
    assert _spec(arm=Arm.CONTROL_B_MARKET_ONLY).spec_hash != base
    assert _spec(mode=ResearchMode.EXPLORATORY).spec_hash != base
    assert _spec(end=END + timedelta(days=1)).spec_hash != base
    assert _spec(hypothesis="other").spec_hash != base


def test_split_not_meaningful_without_forward_data() -> None:
    e = _spec(forward_start=None)
    assert not e.split_meaningful and e.split_note == SPLIT_NOTE_INSUFFICIENT_FORWARD
    short = _spec(forward_start=END - timedelta(days=27))
    assert not short.split_meaningful and short.split_note == SPLIT_NOTE_INSUFFICIENT_FORWARD
    assert _spec(forward_start=END - timedelta(days=28)).split_meaningful


def test_split_not_meaningful_with_too_few_trades() -> None:
    e = _spec(n_trades=24)
    assert not e.split_meaningful and e.split_note == SPLIT_NOTE_INSUFFICIENT_TRADES
    assert _spec(n_trades=25).split_meaningful


def test_experiment_to_dict_is_json_safe() -> None:
    import json

    json.dumps(_spec().to_dict())


@pytest.mark.parametrize(
    ("n", "label"),
    [
        (0, "INSUFFICIENT_SAMPLE"),
        (24, "INSUFFICIENT_SAMPLE"),
        (25, "EXTREMELY_LOW_CONFIDENCE"),
        (50, "EARLY"),
        (100, "PRELIMINARY"),
        (200, "INTERMEDIATE"),
        (499, "INTERMEDIATE"),
        (500, "SUBSTANTIAL"),
    ],
)
def test_sample_label_ladder(n: int, label: str) -> None:
    assert sample_label(n) == label


def test_sample_label_mirrors_the_arena_ladder() -> None:
    """Same floors and labels as app.lab.leaderboard, so a Lab result and an
    Arena result with the same trade count read the same."""
    from app.lab.leaderboard import confidence

    for n in (0, 1, 24, 25, 49, 50, 99, 100, 199, 200, 499, 500, 10_000):
        assert sample_label(n) == confidence(n)


def test_multiple_testing_note() -> None:
    assert multiple_testing_note(1) is None
    assert multiple_testing_note(MULTIPLE_TESTING_THRESHOLD) is None
    note = multiple_testing_note(10)
    assert note is not None
    assert "POSSIBLE MULTIPLE-TESTING / SELECTION BIAS" in note
    assert "0.005" in note
