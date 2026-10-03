"""The research-status gate: what has to be true before an analysis may mean anything.

Each test pins a promise rather than a mechanism: the thresholds are the ones
written into the design doc before any result existed (a quiet edit fails
here); a requirement nobody could measure is unmet, never assumed; the verdict
is UNCERTAIN in every reachable state because no verdict engine exists; and the
two states that presuppose one cannot be reached.
"""

from __future__ import annotations

import itertools
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.lifecycle_lab import research_status as rs
from app.lifecycle_lab.research_status import (
    ExperimentRef,
    GateFacts,
    ResearchState,
    evaluate,
)

pytestmark = pytest.mark.unit

FS = datetime(2026, 10, 1, tzinfo=UTC)
CUTOFF = FS + timedelta(days=90)
EXPERIMENT = ExperimentRef(experiment_key="mll-forward-test-baseline", data_cutoff=CUTOFF)
DOC = Path(__file__).resolve().parents[3] / "docs" / "MEME_LIFECYCLE_LAB.md"


def full_facts(span_days: float = 91, **over: object) -> GateFacts:
    base: dict[str, object] = {
        "forward_span": timedelta(days=span_days),
        "independent_events": 100,
        "revival_events": 30,
        "baseline_trades": 100,
        "oos_trades": 30,
        "distinct_memes": 10,
        "top_meme_share": Decimal("0.25"),
        "control_arms_completed": frozenset("BCD"),
    }
    base.update(over)
    return GateFacts(**base)  # type: ignore[arg-type]


def run(
    now: datetime,
    facts: GateFacts,
    *,
    enabled: bool = True,
    forward_start: datetime | None = FS,
    experiment: ExperimentRef | None = EXPERIMENT,
) -> rs.ResearchStatus:
    return evaluate(
        now=now,
        lab_enabled=enabled,
        forward_start=forward_start,
        experiment=experiment,
        facts=facts,
    )


def met(status: rs.ResearchStatus) -> dict[str, bool]:
    return {r.key: r.met for r in status.requirements}


# --------------------------------------------------------------------------
# Thresholds are pinned to the doc
# --------------------------------------------------------------------------


def test_thresholds_equal_the_documented_table() -> None:
    """Fixed before any result was seen. Changing one is tuning, and tuning
    against the data the Lab will be judged on is the bias this gate prevents."""
    assert rs.FORWARD_HORIZON_DAYS == 90
    assert rs.MIN_INDEPENDENT_EVENTS == 100
    assert rs.MIN_REVIVAL_EVENTS == 30
    assert rs.MIN_BASELINE_TRADES == 100
    assert rs.MIN_OOS_TRADES == 30
    assert rs.MIN_DISTINCT_MEMES == 10
    assert Decimal("0.25") == rs.MAX_TOP_MEME_SHARE
    assert rs.REQUIRED_CONTROL_ARMS == ("B", "C", "D")
    assert rs.COLLECTING_DAYS == 7


def test_the_doc_table_still_says_what_the_constants_say() -> None:
    """The constants are checked against the doc itself when it is reachable
    (it is not mounted in the backend container)."""
    if not DOC.exists():
        pytest.skip("docs/ is not mounted")
    text = DOC.read_text()
    section = text.split("## MINIMUM EVIDENCE REQUIREMENTS", 1)[1].split("## NEW API", 1)[0]
    rows = {
        line.split("|")[1].strip(): line.split("|")[2]
        for line in section.splitlines()
        if line.startswith("| ") and not line.startswith("| Requirement") and "---" not in line
    }

    def number(label_prefix: str) -> int:
        cell = next(v for k, v in rows.items() if k.startswith(label_prefix))
        return int(re.search(r"\d+", cell.replace("`", "")).group())  # type: ignore[union-attr]

    assert number("Independent meme events") == rs.MIN_INDEPENDENT_EVENTS
    assert number("Revival") == rs.MIN_REVIVAL_EVENTS
    assert number("Trades (baseline") == rs.MIN_BASELINE_TRADES
    assert number("Out-of-sample") == rs.MIN_OOS_TRADES
    assert number("Distinct memes") == rs.MIN_DISTINCT_MEMES
    assert Decimal(number("Single-meme")) / 100 == rs.MAX_TOP_MEME_SHARE
    assert "B, C, D" in next(v for k, v in rows.items() if k.startswith("Control arms"))
    assert "MLL_EXPERIMENT_HORIZON_DAYS" in next(
        v for k, v in rows.items() if k.startswith("Forward observation")
    )


def test_every_documented_requirement_has_a_row() -> None:
    status = run(FS + timedelta(days=91), full_facts())
    assert [r.key for r in status.requirements] == list(rs.REQUIREMENT_KEYS)
    assert len(status.requirements) == 8
    for r in status.requirements:
        assert r.label and r.threshold


# --------------------------------------------------------------------------
# State transitions
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("enabled", "forward_start", "now", "why"),
    [
        (False, FS, FS + timedelta(days=30), "switched off"),
        (True, None, FS + timedelta(days=30), "not set"),
        (True, FS, FS - timedelta(days=1), "future"),
    ],
)
def test_not_started(
    enabled: bool, forward_start: datetime | None, now: datetime, why: str
) -> None:
    # Even facts that would satisfy every requirement cannot count before the epoch.
    status = run(now, full_facts(), enabled=enabled, forward_start=forward_start)
    assert status.state is ResearchState.NOT_STARTED, why
    assert all(not r.met and r.observed is None and r.reason for r in status.requirements)


def test_not_started_when_forward_start_is_unset_has_no_forward_days() -> None:
    status = run(FS, GateFacts(), forward_start=None, experiment=None)
    assert status.forward_days is None
    assert status.forward_start is None


def test_collecting_before_seven_days() -> None:
    status = run(FS + timedelta(days=3, hours=12), GateFacts(forward_span=timedelta(days=3.5)))
    assert status.state is ResearchState.COLLECTING
    assert status.forward_days == 3.5
    assert status.experiment_key == EXPERIMENT.experiment_key
    # Unmeasured facts are reported, not hidden, even while it is too early.
    assert len(status.requirements) == 8


def test_collecting_wins_over_met_requirements_inside_the_first_week() -> None:
    """Too early to judge any requirement, whatever the counts say."""
    status = run(FS + timedelta(days=6, hours=23), full_facts(span_days=6.99))
    assert status.state is ResearchState.COLLECTING


def test_insufficient_data_from_day_seven() -> None:
    status = run(FS + timedelta(days=7), GateFacts(forward_span=timedelta(days=7)))
    assert status.state is ResearchState.INSUFFICIENT_DATA


def test_insufficient_data_until_every_requirement_is_met() -> None:
    now = CUTOFF + timedelta(days=1)
    assert run(now, full_facts()).state is ResearchState.READY_FOR_ANALYSIS
    for key in rs.REQUIREMENT_KEYS:
        over = {
            rs.KEY_FORWARD_PERIOD: {"forward_span": timedelta(days=89)},
            rs.KEY_INDEPENDENT_EVENTS: {"independent_events": 99},
            rs.KEY_REVIVAL_EVENTS: {"revival_events": 29},
            rs.KEY_BASELINE_TRADES: {"baseline_trades": 99},
            rs.KEY_OOS_TRADES: {"oos_trades": 29},
            rs.KEY_DISTINCT_MEMES: {"distinct_memes": 9},
            rs.KEY_CONCENTRATION: {"top_meme_share": Decimal("0.2501")},
            rs.KEY_CONTROL_ARMS: {"control_arms_completed": frozenset("BC")},
        }[key]
        status = run(now, full_facts(**over))
        assert status.state is ResearchState.INSUFFICIENT_DATA, key
        assert [r.key for r in status.requirements if not r.met] == [key]


def test_ready_for_analysis_requires_the_data_cutoff_to_have_passed() -> None:
    facts = full_facts(span_days=90)
    assert run(CUTOFF - timedelta(seconds=1), facts).state is ResearchState.INSUFFICIENT_DATA
    assert run(CUTOFF, facts).state is ResearchState.READY_FOR_ANALYSIS


def test_ready_for_analysis_without_a_registered_experiment_is_not_possible() -> None:
    status = run(CUTOFF + timedelta(days=1), full_facts(), experiment=None)
    assert status.state is ResearchState.INSUFFICIENT_DATA
    forward = next(r for r in status.requirements if r.key == rs.KEY_FORWARD_PERIOD)
    assert not forward.met and forward.reason


def test_thresholds_are_inclusive_at_the_boundary() -> None:
    status = run(CUTOFF, full_facts(span_days=90))
    assert all(r.met for r in status.requirements)


def test_the_experiments_own_horizon_is_what_is_enforced() -> None:
    short = ExperimentRef("k", data_cutoff=FS + timedelta(days=30))
    status = run(FS + timedelta(days=31), full_facts(span_days=31), experiment=short)
    forward = next(r for r in status.requirements if r.key == rs.KEY_FORWARD_PERIOD)
    assert forward.threshold == "30 days and data_cutoff passed"
    assert forward.met


def test_default_threshold_text_uses_the_documented_horizon() -> None:
    status = run(FS + timedelta(days=8), GateFacts(), experiment=None)
    forward = next(r for r in status.requirements if r.key == rs.KEY_FORWARD_PERIOD)
    assert forward.threshold == "90 days and data_cutoff passed"


# --------------------------------------------------------------------------
# The verdict engine does not exist
# --------------------------------------------------------------------------


def _grid() -> list[rs.ResearchStatus]:
    out = []
    for enabled, start, day, facts in itertools.product(
        (True, False),
        (FS, None),
        (-1, 0, 3, 7, 60, 90, 400),
        (GateFacts(), full_facts(span_days=1), full_facts(span_days=400)),
    ):
        out.append(
            run(
                FS + timedelta(days=day),
                facts,
                enabled=enabled,
                forward_start=start,
            )
        )
    return out


def test_verdict_is_always_uncertain_and_the_engine_is_unavailable() -> None:
    statuses = _grid()
    assert statuses
    assert {s.verdict for s in statuses} == {"UNCERTAIN"}
    assert {s.verdict_engine_available for s in statuses} == {False}


def test_analyzing_and_authoritative_result_are_unreachable() -> None:
    """They presuppose an analysis run and a verdict engine, neither of which
    exists. Reaching them must be a deliberate code change here, so this fails
    loudly if a transition ever appears."""
    assert {
        ResearchState.ANALYZING,
        ResearchState.AUTHORITATIVE_RESULT,
    } == rs.UNREACHABLE_STATES
    reached = {s.state for s in _grid()}
    assert reached.isdisjoint(rs.UNREACHABLE_STATES)
    assert reached == {
        ResearchState.NOT_STARTED,
        ResearchState.COLLECTING,
        ResearchState.INSUFFICIENT_DATA,
        ResearchState.READY_FOR_ANALYSIS,
    }


def test_the_state_names_match_the_contract() -> None:
    assert [s.value for s in ResearchState] == [
        "NOT_STARTED",
        "COLLECTING",
        "INSUFFICIENT_DATA",
        "READY_FOR_ANALYSIS",
        "ANALYZING",
        "AUTHORITATIVE_RESULT",
    ]


# --------------------------------------------------------------------------
# Unmeasurable is unmet
# --------------------------------------------------------------------------


def test_unmeasurable_requirements_are_unmet_with_a_reason() -> None:
    now = CUTOFF + timedelta(days=1)
    facts = GateFacts(
        forward_span=timedelta(days=91), reasons={rs.KEY_BASELINE_TRADES: "No baseline run."}
    )
    status = run(now, facts)
    by = {r.key: r for r in status.requirements}
    for key in (
        rs.KEY_INDEPENDENT_EVENTS,
        rs.KEY_REVIVAL_EVENTS,
        rs.KEY_BASELINE_TRADES,
        rs.KEY_OOS_TRADES,
        rs.KEY_DISTINCT_MEMES,
        rs.KEY_CONCENTRATION,
        rs.KEY_CONTROL_ARMS,
    ):
        assert by[key].met is False
        assert by[key].observed is None
        assert by[key].reason
    assert by[rs.KEY_BASELINE_TRADES].reason == "No baseline run."
    assert status.state is ResearchState.INSUFFICIENT_DATA


def test_zero_is_measured_and_unmet_not_unmeasurable() -> None:
    status = run(
        CUTOFF + timedelta(days=1), full_facts(baseline_trades=0, independent_events=0)
    )
    by = {r.key: r for r in status.requirements}
    assert by[rs.KEY_BASELINE_TRADES].observed == "0"
    assert by[rs.KEY_BASELINE_TRADES].met is False
    assert by[rs.KEY_INDEPENDENT_EVENTS].observed == "0"


def test_concentration_reports_a_percentage_and_boundary_is_inclusive() -> None:
    at_limit = run(CUTOFF, full_facts(span_days=90))
    c = next(r for r in at_limit.requirements if r.key == rs.KEY_CONCENTRATION)
    assert c.observed == "25.0%" and c.met
    over = run(CUTOFF, full_facts(span_days=90, top_meme_share=Decimal("0.3333")))
    c = next(r for r in over.requirements if r.key == rs.KEY_CONCENTRATION)
    assert c.observed == "33.3%" and not c.met and c.reason


def test_control_arms_report_which_are_missing() -> None:
    status = run(CUTOFF, full_facts(span_days=90, control_arms_completed=frozenset("B")))
    c = next(r for r in status.requirements if r.key == rs.KEY_CONTROL_ARMS)
    assert c.observed == "B"
    assert c.reason is not None and "C, D" in c.reason


def test_explanations_describe_and_never_advise() -> None:
    advice = re.compile(r"\b(buy|sell|hold|consider|recommend)", re.IGNORECASE)
    for status in _grid():
        assert status.explanation
        assert not advice.search(status.explanation)
        for r in status.requirements:
            assert not advice.search(" ".join(filter(None, [r.label, r.threshold, r.reason])))


# --------------------------------------------------------------------------
# Episode counting
# --------------------------------------------------------------------------

T0 = datetime(2026, 10, 10, tzinfo=UTC)


def test_each_wave_is_one_independent_event_and_attention_types_are_not_counted() -> None:
    events = [
        ("m1", "new_attention_wave", T0),
        ("m1", "second_wave", T0 + timedelta(days=3)),
        ("m2", "new_attention_wave", T0),
    ]
    assert rs.count_independent_events(events) == 3


def test_a_revival_beside_a_wave_is_the_same_episode() -> None:
    events = [
        ("m1", "new_attention_wave", T0),
        ("m1", "meme_revival", T0 + timedelta(hours=2)),
        # Another meme's wave does not absorb m1's revival.
        ("m2", "meme_revival", T0 + timedelta(hours=2)),
        # Same meme, but a different day: a separate episode.
        ("m1", "meme_revival", T0 + timedelta(days=5)),
    ]
    assert rs.count_independent_events(events) == 3


def test_duplicate_rows_are_one_event() -> None:
    row = ("m1", "second_wave", T0)
    assert rs.count_independent_events([row, row]) == 1
    assert rs.count_later_wave_events([row, row]) == 1


def test_later_wave_events_are_revival_second_and_third_only() -> None:
    events = [
        ("m1", "new_attention_wave", T0),
        ("m1", "second_wave", T0 + timedelta(days=2)),
        ("m1", "third_wave", T0 + timedelta(days=4)),
        ("m2", "meme_revival", T0),
    ]
    assert rs.count_later_wave_events(events) == 3
