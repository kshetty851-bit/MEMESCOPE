"""HQ watching the Compound Lab — the tournament nothing watched.

It ran on production for hours with no probe, no condition and no repair. Every
signal the Lab has means the same thing for it: a frozen book, a halted tick,
silence where decisions should be. What it does NOT share is a name, and these
tests are mostly about keeping the two apart — an incident that said "the Lab"
while meaning the other one sends somebody to the wrong book.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.compound import spec as cspec
from app.hq_ops import service
from app.hq_ops.remediation import REMEDIATIONS
from app.hq_ops.schemas import (
    ComponentHealth,
    DiskHealth,
    LabHealthRow,
    OperationsHealth,
    QueueHealth,
    SchedulerHealth,
    WorkerHealth,
)
from app.lab import spec as v7spec

pytestmark = pytest.mark.unit


def _health(*, compound=None, lab=None):
    ok = ComponentHealth(component="x", status="healthy", detail="", measured=True)
    return OperationsHealth(
        disk=DiskHealth(status="healthy", percent_used=10.0, warning_percent=80,
                        critical_percent=90, detail="", measured=True),
        redis=ok, database=ok,
        worker=WorkerHealth(status="healthy", nodes=["a"], replies=1, detail="",
                            measured=True),
        scheduler=SchedulerHealth(status="healthy", last_beat=None,
                                  seconds_since_beat=1.0,
                                  expected_within_seconds=120, detail="",
                                  measured=True),
        queues=QueueHealth(status="healthy", depths={}, total=0, detail="",
                           measured=True),
        lab=lab, compound=compound,
        overall="healthy", unmeasured=0, environment="test", version="0",
        observed_at=datetime.now(UTC),
    )


def _sigs(h):
    return {c.signature: c for c in service.detect(h)}


def test_a_halted_compound_lab_is_critical_and_has_no_repair():
    """The two ways out — revert the spec edit, or activate a new tournament —
    are different experiments. The second abandons the record the first keeps,
    and nothing autonomous should choose between them."""
    found = _sigs(_health(compound=LabHealthRow(
        measured=True, detail="", open_positions=2, spec_hash_drift=True,
        stored_spec_hash="a" * 64, running_spec_hash="b" * 64,
        spec_version=cspec.SPEC_VERSION)))
    c = found["compound:spec-drift"]
    assert c.severity == "critical"
    assert c.remediation is None


def test_a_halt_suppresses_the_signals_it_causes():
    """A halted tick makes no decisions and marks nothing, so the silence and
    staleness checks would fire an hour later pointing at the wrong fault."""
    found = _sigs(_health(compound=LabHealthRow(
        measured=True, detail="", open_positions=9, stale_positions=9,
        stale_pct=100.0, minutes_since_decision=999.0, spec_hash_drift=True,
        stored_spec_hash="a" * 64, running_spec_hash="b" * 64)))
    assert "compound:spec-drift" in found
    assert "compound:book-unmarkable" not in found
    assert "compound:no-decisions" not in found


def test_a_frozen_book_is_reported_because_it_can_bank_a_false_cycle():
    """The reason this matters more here than in the Lab: the cycle target is
    tested against these marks, so a frozen book can bank a cycle at a price no
    seller would have been offered."""
    found = _sigs(_health(compound=LabHealthRow(
        measured=True, detail="", open_positions=10, stale_positions=8,
        stale_pct=80.0, spec_hash_drift=False)))
    c = found["compound:book-unmarkable"]
    assert c.remediation == "lab.refresh_marks", (
        "one sweep re-quotes every live tournament, so the Lab's repair is this "
        "one's too"
    )


def test_a_silent_tick_is_repairable():
    found = _sigs(_health(compound=LabHealthRow(
        measured=True, detail="", open_positions=3,
        minutes_since_decision=200.0, spec_hash_drift=False)))
    assert found["compound:no-decisions"].remediation == "compound.run_tick"


def test_an_unmeasured_compound_lab_raises_nothing():
    """Consistent with every other probe: a broken probe must not generate a
    stream of incidents about itself."""
    found = _sigs(_health(compound=LabHealthRow(measured=False, detail="nope")))
    assert not [s for s in found if s.startswith("compound:")]


def test_a_missing_compound_row_raises_nothing():
    """Payloads written before this probe existed must still detect cleanly."""
    assert not [s for s in _sigs(_health()) if s.startswith("compound:")]


def test_the_two_tournaments_never_share_a_signature():
    """An incident naming 'the Lab' while meaning the other one sends somebody
    to the wrong book."""
    both = _sigs(_health(
        compound=LabHealthRow(measured=True, detail="", open_positions=5,
                              stale_positions=5, stale_pct=100.0,
                              spec_hash_drift=False),
        lab=LabHealthRow(measured=True, detail="", open_positions=5,
                         stale_positions=5, stale_pct=100.0,
                         spec_hash_drift=False)))
    assert "compound:book-unmarkable" in both
    assert "lab:book-unmarkable" in both


def test_the_repair_only_re_enqueues_the_compound_beat_task():
    """Called, not read: the assertion is what it DOES."""
    import inspect

    from app.hq_ops import remediation as rem

    sent: list[str] = []
    original = rem._enqueue
    rem._enqueue = lambda name, *a, **k: sent.append(name)  # type: ignore[assignment]
    try:
        result = REMEDIATIONS["compound.run_tick"].execute()
        if inspect.isawaitable(result):
            import asyncio

            asyncio.get_event_loop().run_until_complete(result)
    finally:
        rem._enqueue = original  # type: ignore[assignment]

    assert sent == ["app.compound.scheduler.compound_tick"]


def test_the_repair_is_karthiks_and_may_run_unattended():
    r = REMEDIATIONS["compound.run_tick"]
    assert r.agent == "karthik"
    assert r.autonomy == "green"


def test_the_registries_are_distinct_so_neither_rescores_the_other():
    assert cspec.SPEC_HASH != v7spec.SPEC_HASH
    assert cspec.SPEC_VERSION != v7spec.SPEC_VERSION
