"""The Lab's beat was green while 72% of its book sat frozen.

Liveness said the tick ran. It did. What it had stopped doing was measuring:
162 of 224 open positions were skipped every pass as stale, and the skip is
self-selecting in the worst way — a dying token stops being enriched, so its
snapshot goes stale, so it is never marked again. The positions this hid were
exactly the ones that mattered.

These four signals exist so that has a name the next time it happens.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.hq_ops import service
from app.hq_ops.schemas import LabHealthRow
from app.lab import health

pytestmark = pytest.mark.unit


def _health(**lab):
    """OperationsHealth with everything quiet except the Lab row under test."""
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
        lab=LabHealthRow(measured=True, detail="", **lab),
        overall="healthy", unmeasured=0, environment="test", version="0",
        observed_at=datetime.now(UTC),
    )


def _signatures(health_reading) -> set[str]:
    return {c.signature for c in service.detect(health_reading)}


def test_a_frozen_book_is_reported():
    """The actual failure: 162 of 224 unmarkable, and nothing said so."""
    found = _signatures(_health(open_positions=224, stale_positions=162, stale_pct=72.3,
                                quote_backed_pct=100.0))
    assert "lab:book-unmarkable" in found


def test_ordinary_staleness_is_not_a_condition():
    """Some staleness is normal — a token stops being enriched the moment it
    stops mattering. A watch that fires on the normal case is one nobody reads."""
    found = _signatures(_health(open_positions=100, stale_positions=12, stale_pct=12.0,
                                quote_backed_pct=100.0))
    assert "lab:book-unmarkable" not in found


def test_a_model_priced_book_is_reported():
    """The CPMM model priced dying positions at cost. The leaderboard is what a
    real strategy gets chosen from, so how much of it rests on that model is
    the question worth asking."""
    found = _signatures(_health(open_positions=50, stale_positions=0, stale_pct=0.0,
                                quote_backed_pct=20.0))
    assert "lab:marks-unverified" in found


def test_entries_and_exits_stopping_are_different_faults():
    """Both look identical from outside — a beat that keeps ticking — so they
    get separate signatures and separate sentences."""
    silent = _signatures(_health(open_positions=10, stale_positions=0, stale_pct=0.0,
                                 quote_backed_pct=100.0,
                                 minutes_since_decision=240.0,
                                 minutes_since_close=600.0))
    assert "lab:no-decisions" in silent
    assert "lab:no-closes" in silent


def test_an_empty_book_does_not_report_stalled_exits():
    """Nothing has closed because nothing is open. That is not a fault."""
    found = _signatures(_health(open_positions=0, stale_positions=0, stale_pct=0.0,
                                quote_backed_pct=100.0, minutes_since_close=99_999.0))
    assert "lab:no-closes" not in found


def test_an_unmeasured_lab_raises_nothing():
    """Consistent with every other probe: an unmeasured component is not an
    incident, or a broken probe generates a stream of incidents about itself."""
    reading = _health(open_positions=1, stale_pct=99.0)
    reading = reading.model_copy(update={
        "lab": LabHealthRow(measured=False, detail="could not read")
    })
    assert not any(c.signature.startswith("lab:") for c in service.detect(reading))


def test_a_lab_remediation_may_only_restart_the_labs_own_schedule():
    """This test used to read "the Lab never gets a remediation", on the
    grounds that acting on a tournament changes the experiment being observed.

    That was right about the danger and wrong about the boundary. Held
    literally it meant a wedged queue stopped the tournament and HQ watched it
    happen — and a tournament that silently stopped is not a preserved
    experiment, it is a lost one. All four `lab:` conditions sat on
    `remediation=None` for exactly this reason.

    So the line moved from WHETHER HQ may act to WHAT it may do: re-run the
    Lab's own scheduled work, never change what that work does. Re-enqueueing
    `lab_tick` cannot open a position, close one, pick a strategy or edit the
    frozen spec — it makes work that was already due happen now instead of
    never. The original concern survives as the assertion below.
    """
    reading = _health(open_positions=224, stale_positions=200, stale_pct=89.0,
                      quote_backed_pct=5.0, minutes_since_decision=999.0,
                      minutes_since_close=999.0)
    seen = 0
    for condition in service.detect(reading):
        if not condition.signature.startswith("lab:"):
            continue
        seen += 1
        assert condition.remediation is not None, condition.signature
        assert condition.remediation in ("lab.run_tick", "lab.refresh_marks"), (
            f"{condition.signature} reaches beyond re-running the Lab's own "
            f"schedule: {condition.remediation}"
        )
    assert seen, "the fixture is meant to trip the lab conditions"


def test_unmeasurable_is_never_reported_as_zero():
    """"No stale positions" and "the stale positions could not be counted" are
    opposite readings, and displaying the second as the first is the failure
    this module exists to catch."""
    src = Path(health.__file__).read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "read")
    handler = next(h for n in ast.walk(fn) if isinstance(n, ast.Try) for h in n.handlers)
    body = ast.unparse(handler)
    assert "measured=False" in body
    assert "0" not in body.replace("LabHealth", "")


def test_mark_quality_is_weighted_by_value_not_by_count():
    """Ten dust positions quote-backed and one large one on the model is not a
    well-evidenced book, and a count would call it 91% healthy."""
    src = ast.unparse(ast.parse(Path(health.__file__).read_text()))
    assert "backed / total" in src


def test_the_staleness_rule_is_the_lab_s_own():
    """Counted the same way `_mark` decides to skip a position, so this number
    IS what the next tick will refuse to evaluate — not an approximation."""
    src = Path(health.__file__).read_text()
    assert "STALE_GUARD_SECONDS" in src
    assert "from app.lab.execution import" in src


def test_the_lab_probe_does_not_share_the_caller_s_session():
    """The probes run concurrently and a SQLAlchemy session is not safe for
    concurrent use.

    Sharing the caller's put this probe and `_probe_database` on the same
    connection, and the first snapshot after it shipped failed with "concurrent
    operations are not permitted" — reported honestly as unmeasured, and
    measuring nothing.
    """
    from app.hq_ops import probe

    src = Path(probe.__file__).read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_probe_lab")
    # It takes no session, and opens one of its own.
    assert [a.arg for a in fn.args.args] == ["now"]
    assert "SessionFactory()" in ast.unparse(fn)


def test_a_quoted_position_is_not_counted_as_unmarkable():
    """A stale SNAPSHOT stopped being disqualifying when `_mark` began
    consulting a fresh sell quote first — that was the fix for the frozen book.

    Counting stale snapshots alone measured the behaviour that was replaced. It
    reported 57% unmarkable on a book that was 100% quote-backed, which is a
    watch describing a fault that no longer exists.
    """
    src = Path(health.__file__).read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_unmarkable_count")
    body = ast.unparse(fn)
    # Unmarkable requires BOTH to be absent.
    assert "not in fresh and mint not in quoted" in body
    assert "quoted" in {a.arg for a in fn.args.args}
