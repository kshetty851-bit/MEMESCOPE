"""HQ must watch the labs that are RUNNING, not the ones it was written for.

On 2026-09-08 HQ reported on V7 and the Compound Lab — both deliberately
stopped — and on neither PumpFun nor the control arm that had replaced them.
Two of its three live conditions were permanent alarms for tournaments nobody
wanted running, which is the alarm fatigue that makes a watch worthless.

The fix is that "which labs exist" is DERIVED from the feature flags rather
than written at the call site, so it cannot drift again.
"""

from __future__ import annotations

import pytest

from app.hq_ops.probe import LAB_REGISTRIES, _lab_is_running


def _flags(monkeypatch, **values):
    from app.core.config import settings
    monkeypatch.setattr(settings, "FEATURE_LAB_ENABLED", values.pop("master", True))
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)


def test_every_registry_that_exists_is_watchable():
    """A lab absent from this table is invisible to HQ, and the failure is
    silent — it looks exactly like a lab that is quiet."""
    import importlib
    import pkgutil

    import app

    known = {module for _, module, _ in LAB_REGISTRIES}
    found = set()
    for mod in pkgutil.iter_modules(app.__path__):
        if not mod.ispkg:
            continue
        try:
            registry = importlib.import_module(f"app.{mod.name}.spec")
        except ModuleNotFoundError:
            continue
        if hasattr(registry, "SPEC_VERSION") and hasattr(registry, "STRATEGIES"):
            found.add(f"app.{mod.name}.spec")

    assert found <= known, f"these labs exist but HQ cannot see them: {found - known}"


def test_each_registry_names_a_real_flag():
    from app.core.config import settings

    for label, _module, flag in LAB_REGISTRIES:
        assert hasattr(settings, flag), f"{label} names a flag that does not exist: {flag}"


def test_a_lab_needs_both_its_own_switch_and_the_master(monkeypatch):
    _flags(monkeypatch, master=True, FEATURE_PUMPFUN_LAB_ENABLED=True)
    assert _lab_is_running("FEATURE_PUMPFUN_LAB_ENABLED") is True

    _flags(monkeypatch, master=False, FEATURE_PUMPFUN_LAB_ENABLED=True)
    assert _lab_is_running("FEATURE_PUMPFUN_LAB_ENABLED") is False, (
        "the master switch gates every lab; a lab cannot run without it"
    )


def test_a_switched_off_lab_is_not_running(monkeypatch):
    _flags(monkeypatch, master=True, FEATURE_V7_LAB_ENABLED=False)
    assert _lab_is_running("FEATURE_V7_LAB_ENABLED") is False


async def test_a_stopped_lab_is_absent_rather_than_reported_quiet(monkeypatch):
    """THE fix. A row for a stopped tournament reads as silence where there
    should be decisions, and every downstream check then fires forever on
    something nobody wanted running."""
    from app.hq_ops import probe

    _flags(monkeypatch, master=True,
           FEATURE_V7_LAB_ENABLED=False,
           FEATURE_COMPOUND_LAB_ENABLED=False,
           FEATURE_MOMENTUM_LAB_ENABLED=False,
           FEATURE_DEPTH_LAB_ENABLED=False,
           FEATURE_SOCIAL_LAB_ENABLED=False,
           FEATURE_PUMPFUN_LAB_ENABLED=False,
           FEATURE_COPYCONTROL_ENABLED=False)

    from datetime import UTC, datetime
    rows = await probe._probe_labs(datetime.now(UTC))
    assert rows == [], "no lab is running, so there is nothing to report"


async def test_the_v7_probe_reports_unmeasured_when_v7_is_off(monkeypatch):
    """`lab:no-decisions` guards on `lab.measured`, so an unmeasured row is what
    stops the permanent alarm."""
    from datetime import UTC, datetime

    from app.hq_ops import probe

    _flags(monkeypatch, master=True, FEATURE_V7_LAB_ENABLED=False)
    row = await probe._probe_lab(datetime.now(UTC))
    assert row.measured is False
    assert row.label == "V7"
    assert "switched off" in row.detail


async def test_the_compound_probe_reports_unmeasured_when_it_is_off(monkeypatch):
    from datetime import UTC, datetime

    from app.hq_ops import probe

    _flags(monkeypatch, master=True, FEATURE_COMPOUND_LAB_ENABLED=False)
    row = await probe._probe_compound(datetime.now(UTC))
    assert row.measured is False and row.label == "Compound"


def test_every_row_carries_a_label():
    """A list of anonymous rows is a list of numbers. An incident that named
    'the Lab' while meaning another one sends somebody to the wrong book."""
    from app.hq_ops.schemas import LabHealthRow

    assert "label" in LabHealthRow.model_fields
