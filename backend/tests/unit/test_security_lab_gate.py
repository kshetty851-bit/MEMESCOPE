"""The security gate, and the two ways it could quietly stop being a gate.

The lab spends its losses on rugs — five of fifty closed trades, -$76 against
+$113 from everything else — and the platform already had an evaluator that
nothing pointed at those coins. These tests hold the gate to the policy the
evaluator itself states: every check must positively PASS.
"""

from __future__ import annotations

from decimal import Decimal as D

from app.movers import spec


def test_the_pair_differs_by_the_security_condition_alone() -> None:
    gated = {str(c) for c in spec.BY_ID["MOV-03"].entry}
    control = {str(c) for c in spec.BY_ID["MOV-04"].entry}
    assert gated - control == {str(spec._SECURE)}
    assert control - gated == set()


def test_the_control_is_the_pool_alone() -> None:
    """Any extra condition on the control and the pair differs in two ways."""
    assert spec.BY_ID["MOV-04"].entry == spec._POOL


def test_the_gate_demands_a_positive_verdict() -> None:
    """`>= 1` where 1 is VERIFIED alone. If this ever became `>= 0`, or the
    feature started counting UNKNOWN as a pass, the arm would look gated and
    buy everything — the failure that leaves no trace in a result."""
    c = next(c for c in spec.BY_ID["MOV-03"].entry
             if c.feature == "security_verified")
    assert c.op == "gte" and c.value == D("1")


def test_a_fresh_version_starts_a_fresh_tournament() -> None:
    """The previous run halted on `spec_hash_drift` when its registry was
    edited underneath it. A new SPEC_VERSION is how that is resolved honestly:
    the old tournament keeps its record and this one starts clean, rather than
    the stored hash being overwritten to make an edited experiment look
    continuous."""
    assert spec.SPEC_VERSION == "movers-6.0.0"
    assert len(spec.SPEC_VERSION) <= 16


def test_all_three_arms_size_identically_and_the_pair_shares_its_clock() -> None:
    assert len({s.size_usd for s in spec.STRATEGIES}) == 1
    assert len({s.max_concurrent for s in spec.STRATEGIES}) == 1
    assert all(s.exits.take_profit is None for s in spec.STRATEGIES)
    # The security pair holds for the same thirty minutes; MOV-05 has no clock
    # at all, which is the one thing that separates it from the control.
    assert (spec.BY_ID["MOV-03"].exits.time_exit_hours
            == spec.BY_ID["MOV-04"].exits.time_exit_hours
            == spec.TIME_EXIT_HOURS)
    assert spec.BY_ID["MOV-05"].exits.time_exit_hours is None


def test_the_board_is_the_pair_and_the_no_clock_arm() -> None:
    """MOV-02 held rules identical to the control and was removed on
    instruction: a line that differs in nothing invites reading whichever is
    ahead as a result. MOV-05 was added on instruction and is the opposite
    case — it differs from the control in exactly one thing, the clock — so
    it is a second comparison rather than a third horse."""
    assert set(spec.BY_ID) == {"MOV-03", "MOV-04", "MOV-05"}
    assert spec.BY_ID["MOV-05"].entry == spec.BY_ID["MOV-04"].entry


# --- the gate the LAB applies must be the gate the REAL WALLET applies ------
#
# Replayed on 2026-09-09 against all 80 movers entries: the real wallet would
# have been allowed to buy 4 of them. MOV-03's entries were 2/2 allowed and
# MOV-04's control 2/22, which is what a control that ignores security should
# look like. These tests keep the gated arm at 2/2 by construction — a paper
# record built on coins the real wallet refuses cannot be acted on, and the
# divergence is invisible in the equity curve.

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.lab.service import LabService
from app.models.token_security import TokenSecurityEvaluationRow
from app.security import entry_policy
from app.security.contract import EVALUATOR_VERSION, CheckName, CheckStatus

_NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
_MINT = "So11111111111111111111111111111111111111112"


def _row(**over) -> TokenSecurityEvaluationRow:
    """A row that passes every mandatory check, unless a test breaks one."""
    checks = [
        {"name": str(n), "status": str(CheckStatus.PASS), "reason_codes": [],
         "detail": "", "evidence": {}}
        for n in entry_policy.MANDATORY_CHECKS
    ]
    fields = dict(
        mint_address=_MINT, evaluated_at=_NOW - timedelta(minutes=3),
        overall_status="VERIFIED", evaluator_version=EVALUATOR_VERSION,
        reason_codes=[], checks=checks, evidence={}, market_snapshot_at=None,
    )
    fields.update(over)
    return TokenSecurityEvaluationRow(**fields)


class _OneRowSession:
    """Returns `row` from any query, and records what was asked for."""

    def __init__(self, row):
        self._row = row
        self.statements = []

    async def execute(self, statement, *a, **kw):
        self.statements.append(str(statement))
        row = self._row

        class _Result:
            def scalar_one_or_none(self_inner):
                return row

        return _Result()


def _verified(row) -> bool:
    session = _OneRowSession(row)
    allowed = asyncio.run(LabService(session)._security_verified(_MINT, _NOW))
    # Point-in-time: a verdict the platform only reached AFTER the checkpoint
    # must not decide the checkpoint. Lookahead here would make every backtest
    # of this arm optimistic in a way no equity curve reveals.
    assert "evaluated_at <=" in session.statements[0]
    return allowed


def test_a_fresh_complete_pass_is_tradeable() -> None:
    assert _verified(_row()) is True


def test_a_stale_verdict_is_not_tradeable() -> None:
    """VERIFIED, every check passed — and 40 minutes old. The venue and
    liquidity checks expire in 15, so the real wallet refuses it; the lab must
    too. The old implementation read `overall_status` and had no clock."""
    assert _verified(_row(evaluated_at=_NOW - timedelta(minutes=40))) is False


def test_an_incomplete_evaluation_is_not_tradeable() -> None:
    """`roll_up` returns VERIFIED when nothing among the checks PRESENT failed,
    so a row missing mandatory checks stores as VERIFIED. `decide` refuses it."""
    partial = [
        {"name": str(CheckName.MINT_AUTHORITY), "status": str(CheckStatus.PASS),
         "reason_codes": [], "detail": "", "evidence": {}}
    ]
    assert _verified(_row(checks=partial)) is False


def test_a_foreign_evaluator_version_is_not_tradeable() -> None:
    assert _verified(_row(evaluator_version="someone-elses-evaluator")) is False


def test_never_evaluated_is_not_tradeable() -> None:
    assert _verified(None) is False
