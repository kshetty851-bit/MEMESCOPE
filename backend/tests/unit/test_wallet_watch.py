"""Money that left without going through the rail.

Every guard in this wallet sits in FRONT of the rail and asks whether a spend
may proceed — twenty-two conditions in the submission guard alone. None of them
notices a key used somewhere else, because nothing that happens outside the rail
passes through them.

That is a different KIND of question from everything else HQ watches. A wedged
worker is operations. A wallet lighter than the rail can account for is security.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.hq_ops import service
from app.hq_ops.schemas import WalletHealthRow
from app.real_wallet import balance_watch, wallet_health

pytestmark = pytest.mark.unit


def _health(**wallet):
    from app.hq_ops.schemas import (
        ComponentHealth,
        DiskHealth,
        OperationsHealth,
        QueueHealth,
        SchedulerHealth,
        WorkerHealth,
    )

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
        wallet=WalletHealthRow(measured=True, detail="", **wallet),
        overall="healthy", unmeasured=0, environment="test", version="0",
        observed_at=datetime.now(UTC),
    )


def _found(reading):
    return {c.signature: c for c in service.detect(reading)}


def test_an_unexplained_decrease_is_critical():
    """The one wallet signal that is security rather than health, and the only
    one that is critical."""
    found = _found(_health(balance_unexplained=True,
                           balance_delta_lamports=-42_000_000,
                           balance_lamports=8_000_000))
    condition = found["wallet:balance-unexplained"]
    assert condition.severity == "critical"
    # There is nothing safe to do automatically: anything that could move funds
    # in response is the same capability that may already be being misused.
    assert condition.remediation is None


def test_a_deposit_is_never_an_alarm():
    """Deposits are open by design — the address is public and anyone may send
    to it. Reporting a rise would train the reader to dismiss the alert."""
    found = _found(_health(balance_unexplained=False,
                           balance_delta_lamports=+500_000_000))
    assert "wallet:balance-unexplained" not in found


def test_fee_dust_does_not_raise():
    """Rent and priority fees move the balance constantly. The tolerance is far
    below any trade this wallet is configured to make, so nothing meaningful
    hides beneath it."""
    assert balance_watch.FEE_TOLERANCE_LAMPORTS <= 10_000_000
    src = Path(balance_watch.__file__).read_text()
    assert "delta >= -FEE_TOLERANCE_LAMPORTS" in src


def test_a_submitted_intent_explains_a_decrease():
    """SUBMITTED counts, not only CONFIRMED: a transfer that reached the network
    has already moved the money, and waiting for confirmation would raise a
    false alarm on every trade during the seconds it takes to settle."""
    tree = ast.parse(Path(balance_watch.__file__).read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_rail_activity")
    src = ast.unparse(fn)
    assert "'submitted'" in src and "'confirmed'" in src


def test_an_unreadable_balance_writes_no_observation():
    """A gap in the series is honest. A row saying "nothing moved" when nothing
    was measured is a lie AND becomes the baseline the next check trusts."""
    tree = ast.parse(Path(balance_watch.__file__).read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "observe")
    handler = next(h for n in ast.walk(fn) if isinstance(n, ast.Try) for h in n.handlers)
    body = ast.unparse(handler)
    assert "session.add" not in body
    assert "measured=False" in body


def test_a_first_observation_claims_nothing():
    """There is nothing to compare against, and zero would claim there was."""
    src = Path(balance_watch.__file__).read_text()
    assert "delta: int | None = None" in src
    assert "unexplained: bool | None = None" in src


def test_stuck_intents_are_reported():
    found = _found(_health(stuck_intents=3, oldest_stuck_minutes=47.0))
    assert "wallet:intents-stuck" in found
    assert found["wallet:intents-stuck"].severity == "degraded"


def test_one_slow_step_is_not_a_stall():
    found = _found(_health(stuck_intents=1, oldest_stuck_minutes=2.0))
    assert "wallet:intents-stuck" not in found


def test_a_repeated_refusal_is_a_wall():
    """One rejection is the system working. Forty identical ones is a wall
    nobody can see — which is what `safety:` with nothing after it was, for
    hours, while every intent was blocked."""
    found = _found(_health(repeated_reason="safety:", repeated_count=40))
    assert "wallet:blocked-repeatedly" in found
    assert "safety:" in found["wallet:blocked-repeatedly"].summary


def test_a_handful_of_refusals_is_normal():
    assert "wallet:blocked-repeatedly" not in _found(
        _health(repeated_reason="autotrade_switch_off", repeated_count=3)
    )


def test_an_unmeasured_wallet_raises_nothing():
    reading = _health(stuck_intents=99, oldest_stuck_minutes=999.0)
    reading = reading.model_copy(update={
        "wallet": WalletHealthRow(measured=False, detail="unreadable")
    })
    assert not any(c.signature.startswith("wallet:") for c in service.detect(reading))


def test_no_wallet_condition_has_a_remediation():
    """HQ may restart a worker. Nothing it can do automatically is a safe
    response to a wallet that is short."""
    reading = _health(balance_unexplained=True, balance_delta_lamports=-9,
                      stuck_intents=9, oldest_stuck_minutes=99.0,
                      repeated_reason="x", repeated_count=99)
    for condition in service.detect(reading):
        if condition.signature.startswith("wallet:"):
            assert condition.remediation is None, condition.signature


def test_the_watch_only_ever_records():
    """It writes an observation and decides nothing. There is no code path from
    here to an action on the wallet."""
    # Checked on the PARSE TREE. The docstring explains what submitting and
    # signing are, so a text match fails on the very prose that documents the
    # guarantee — a mistake this codebase has made enough times to be worth
    # naming in the test that avoids it.
    tree = ast.parse(Path(balance_watch.__file__).read_text())
    called = {
        n.func.attr for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    assert not called & {"sign", "sign_withdrawal", "execute_signed_order", "submit"}
    # And it imports nothing that could move money.
    imported: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module)
        elif isinstance(n, ast.Import):
            imported.update(a.name for a in n.names)
    assert not any("signer" in m or "transport" in m or "withdraw_service" in m
                   for m in imported)
