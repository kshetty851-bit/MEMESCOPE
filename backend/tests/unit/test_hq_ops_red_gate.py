"""SCENARIO 3 of the acceptance test: the RED gate.

A protected trading rule changes while HQ is performing an autonomous action.
The requirement is not that HQ notices — it is that HQ *fails the action it
was doing*, refuses to continue, and routes the change to a person.

This is a test rather than a live drill on purpose. Demonstrating it against
the running system would mean writing an incident row saying a protected rule
changed when none did, and a fabricated incident is precisely what §27 of the
brief forbids. The refusal path is proven here, where the tampering is real
within the test and invented nowhere else.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.hq_ops import service
from app.hq_ops.remediation import REMEDIATIONS
from app.models.hq_ops import HqAction, HqIncident
from tests.unit.test_hq_ops_safety import health


@pytest.mark.asyncio
async def test_a_protected_rule_that_moves_mid_action_fails_it_and_escalates(
    db_session, monkeypatch
):
    action = REMEDIATIONS["diagnostics.reprobe"]

    # A healthy stack, so nothing but the invariant check can fail the action.
    async def fake_snapshot(_session, **_kwargs):
        return health()

    monkeypatch.setattr(service, "snapshot", fake_snapshot)

    # The tamper: the second capture reports autotrade switched on. Nothing
    # else about the run changes, so the *only* reason this can fail is the
    # invariant comparison — which is the property under test.
    real_capture = service.invariants.capture
    baseline = real_capture()
    tampered = copy.deepcopy(baseline)
    tampered["values"]["REAL_WALLET_AUTOTRADE_ENABLED"] = "True"
    tampered["digest"] = "tampered"

    calls = {"n": 0}

    def capture_then_tamper():
        calls["n"] += 1
        return baseline if calls["n"] == 1 else tampered

    monkeypatch.setattr(service.invariants, "capture", capture_then_tamper)

    incident, _created = await service.open_incident(
        db_session,
        service.Condition(
            signature="test:drill",
            component="worker",
            severity="degraded",
            summary="Acceptance drill.",
            remediation="diagnostics.reprobe",
            symptoms={},
        ),
    )
    await db_session.commit()

    outcome = await service.run_remediation(
        db_session, action, incident=incident, reason="Acceptance drill."
    )

    # 1. The action failed, even though the action itself did nothing wrong.
    assert outcome.outcome == "failed"
    assert "Protected trading rules changed" in outcome.detail

    # 2. The audit row records the failure and names the field that moved.
    audit = (
        (
            await db_session.execute(
                select(HqAction).where(HqAction.incident_id == incident.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(audit) == 1
    assert audit[0].outcome == "failed"
    changed = audit[0].verification["invariants"]["changed"]
    assert "REAL_WALLET_AUTOTRADE_ENABLED" in changed
    assert changed["REAL_WALLET_AUTOTRADE_ENABLED"]["after"] == "True"

    # 3. A RED incident exists, assigned to Quinn, with a rationale for a person.
    raised = (
        (
            await db_session.execute(
                select(HqIncident).where(HqIncident.signature == "invariants:changed")
            )
        )
        .scalars()
        .all()
    )
    assert len(raised) == 1
    assert raised[0].autonomy == "red"
    assert raised[0].agent == "quinn"
    assert raised[0].status == "open"
    assert "confirms this was an intended deployment" in (raised[0].owner_rationale or "")


@pytest.mark.asyncio
async def test_the_red_incident_is_never_auto_resolved(db_session, monkeypatch):
    """It waits for a person, however healthy the system looks afterwards.

    Every other incident closes when its condition disappears from a fresh
    reading. This one has no condition to disappear — the evidence that a rule
    moved is historical — so a tick that resolved it on "everything looks fine
    now" would be closing an unread message.
    """

    async def fake_snapshot(_session, **_kwargs):
        return health()

    monkeypatch.setattr(service, "snapshot", fake_snapshot)

    incident = HqIncident(
        code="INC-999",
        sequence=999,
        kind="incident",
        component="trading-policy",
        severity="critical",
        status="open",
        autonomy="red",
        agent="quinn",
        signature="invariants:changed",
        symptoms={"summary": "A protected trading rule changed."},
        detected_at=datetime.now(UTC),
    )
    db_session.add(incident)
    await db_session.commit()

    report = await service.tick(db_session)

    assert "INC-999" not in report["resolved"]
    await db_session.refresh(incident)
    assert incident.status == "open"


# ── observe-only ────────────────────────────────────────────────────────


def test_autonomy_is_off_unless_explicitly_armed(monkeypatch):
    """The default decides what a forgotten environment variable means.

    Off by default, so an operator who deploys without knowing about the flag
    gets a system that watches and records and touches nothing. The other way
    round, a forgotten variable is the difference between observation and a
    process that restarts production workers.
    """
    from app.hq_ops.remediation import AUTONOMY_ENV_VAR, autonomy_enabled

    monkeypatch.delenv(AUTONOMY_ENV_VAR, raising=False)
    assert autonomy_enabled() is False

    for value in ["", "false", "0", "no", "off", "banana", "TRUE-ish"]:
        monkeypatch.setenv(AUTONOMY_ENV_VAR, value)
        assert autonomy_enabled() is False, f"{value!r} should not arm execution"

    for value in ["true", "TRUE", "  True  ", "1", "yes", "on"]:
        monkeypatch.setenv(AUTONOMY_ENV_VAR, value)
        assert autonomy_enabled() is True, f"{value!r} should arm execution"


@pytest.mark.asyncio
async def test_observe_only_detects_and_records_but_executes_nothing(
    db_session, monkeypatch
):
    """The whole point of the mode, as one assertion set.

    Everything except the execution still happens: the condition is detected,
    an incident is opened, and it carries a rationale naming the repair that
    would have run. What must not exist afterwards is an audit row — an action
    row is a claim that something ran.
    """
    from app.hq_ops.remediation import AUTONOMY_ENV_VAR
    from app.hq_ops.schemas import WorkerHealth

    monkeypatch.delenv(AUTONOMY_ENV_VAR, raising=False)

    sick = health(
        worker=WorkerHealth(status="down", nodes=[], replies=0, detail="silent"),
        overall="down",
    )

    async def fake_snapshot(_session, **_kwargs):
        return sick

    monkeypatch.setattr(service, "snapshot", fake_snapshot)

    report = await service.tick(db_session)

    assert report["armed"] is False
    assert report["detected"] == ["worker:not-answering"]
    assert len(report["opened"]) == 1
    assert [entry["outcome"] for entry in report["repaired"]] == ["withheld"]

    incident = (
        (
            await db_session.execute(
                select(HqIncident).where(HqIncident.signature == "worker:not-answering")
            )
        )
        .scalars()
        .one()
    )
    assert incident.status == "awaiting_owner"
    assert "observe-only" in (incident.owner_rationale or "")
    assert "worker.pool_restart" in (incident.owner_rationale or "")

    # The load-bearing assertion. No action row means nothing ran, and the
    # audit trail cannot imply otherwise.
    actions = (
        (await db_session.execute(select(HqAction))).scalars().all()
    )
    assert actions == []


@pytest.mark.asyncio
async def test_observe_only_still_closes_incidents_on_evidence(db_session, monkeypatch):
    """Withholding the repair must not withhold the recovery.

    An observe-only HQ that opened incidents and never closed them would grow
    an incident list nobody trusts, which is worse than not having one.
    """
    from app.hq_ops.remediation import AUTONOMY_ENV_VAR
    from app.hq_ops.schemas import WorkerHealth

    monkeypatch.delenv(AUTONOMY_ENV_VAR, raising=False)

    state = {
        "health": health(
            worker=WorkerHealth(status="down", nodes=[], replies=0, detail="silent"),
            overall="down",
        )
    }

    async def fake_snapshot(_session, **_kwargs):
        return state["health"]

    monkeypatch.setattr(service, "snapshot", fake_snapshot)

    opened = await service.tick(db_session)
    code = opened["opened"][0]

    state["health"] = health()
    recovered = await service.tick(db_session)

    assert code in recovered["resolved"]
