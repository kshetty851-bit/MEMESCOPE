"""A halted Lab must say so, not be deduced from an hour of silence.

`lab_tick` returns {"halted": "spec_hash_drift"} on every pass when the running
spec no longer matches the tournament's. Every container stays healthy and the
beat keeps ticking, so before this the first sign was `lab:no-decisions` sixty
minutes later — pointing at the worker, with a remediation that cannot work.
"""

from __future__ import annotations

from app.hq_ops.schemas import LabHealthRow
from app.hq_ops.service import detect
from tests.unit.test_hq_ops_safety import health


def _lab(**kw) -> LabHealthRow:
    base = dict(
        measured=True, detail="x", open_positions=100, stale_positions=0,
        stale_pct=0.0, quote_backed_pct=100.0,
        minutes_since_decision=1.0, minutes_since_close=1.0,
        spec_version="1.2.0", spec_hash_drift=False,
        stored_spec_hash="a" * 64, running_spec_hash="a" * 64,
    )
    base.update(kw)
    return LabHealthRow(**base)


def _drift_conditions(**kw) -> list:
    """Detect against an otherwise-healthy stack, so only the Lab can speak."""
    found = detect(health(lab=_lab(**kw)))
    return [c for c in found if c.signature == "lab:spec-drift"]


class TestTheHaltIsNamed:
    def test_a_drift_raises_its_own_incident(self) -> None:
        assert _drift_conditions(spec_hash_drift=True, stored_spec_hash="b" * 64)

    def test_it_is_critical_because_nothing_trades(self) -> None:
        assert _drift_conditions(spec_hash_drift=True)[0].severity == "critical"

    def test_it_carries_no_remediation(self) -> None:
        """Reverting the edit and activating a new tournament are DIFFERENT
        experiments — the second abandons the record the first preserves.
        Nothing autonomous should choose between them, and re-running the tick
        would simply halt again."""
        assert _drift_conditions(spec_hash_drift=True)[0].remediation is None

    def test_it_names_both_hashes(self) -> None:
        c = _drift_conditions(spec_hash_drift=True, stored_spec_hash="b" * 64)[0]
        assert c.symptoms["running_spec_hash"] == "a" * 64
        assert c.symptoms["stored_spec_hash"] == "b" * 64

    def test_a_matching_spec_raises_nothing(self) -> None:
        assert not _drift_conditions(spec_hash_drift=False)

    def test_an_unmeasured_lab_does_not_claim_a_drift(self) -> None:
        """`None` is unmeasured, and unmeasured is not a halt."""
        assert not _drift_conditions(spec_hash_drift=None)
