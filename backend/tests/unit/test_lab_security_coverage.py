"""The coverage pass must aim at the clock the LABS judge by.

It ran every minute, capped at 25, and still left 158 of 168 lab entries with
no evaluation on disk. The pass worked; it was pointed at the wrong population,
twice on 2026-09-09:

* `LOOKBACK` bounded `captured_at` — "has a recent deep print" — which selects
  coins discovered yesterday and still trading: 67 mints averaging 4.6 hours
  old, reaching 30. Oldest-first, the cap went to coins judged hours earlier.
* Re-bounding on `discovered_at` looked right and was worse. The engine sets
  `checkpoint_at = RadarToken.first_detected_at + checkpoint_minutes`, and
  radar admits a coin 60-76 MINUTES after discovery — so that window held
  coins an hour too YOUNG to be judged, and MOV-03 declined eight consecutive
  candidates with zero evaluations on disk at their checkpoint.

These assertions are on the query the function actually issues, not its source
text. Aim it at the wrong clock again and the cap silently starves the labs
while every dashboard looks healthy.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.security import lab_coverage

_NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


class _CapturingSession:
    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, statement, *a, **kw):
        self.statements.append(str(statement))
        return []


def _sql() -> str:
    session = _CapturingSession()
    asyncio.run(lab_coverage.candidates(session, now=_NOW))
    return session.statements[0]


def test_the_pass_keys_on_RADAR_ADMISSION() -> None:
    """The clock `_due_candidates` sets the checkpoint from. Keying on
    `discovered_tokens.discovered_at` instead is an hour early and evaluates
    coins no lab will judge for another sixty minutes."""
    sql = _sql()
    assert "radar_tokens.first_detected_at >=" in sql
    assert "discovered_tokens.discovered_at" not in sql


def test_the_pass_still_requires_a_recent_deep_print() -> None:
    """Both bounds, not one swapped for the other: a coin admitted to radar but
    no longer deep is not worth an RPC call."""
    sql = _sql()
    assert "token_market_snapshots.captured_at >=" in sql
    assert "token_market_snapshots.liquidity_usd >=" in sql


def test_the_lookback_covers_the_checkpoint_with_room() -> None:
    """The labs judge ten minutes after ADMISSION. A lookback under that would
    drop coins before the decision that needs them."""
    assert lab_coverage.LOOKBACK.total_seconds() / 60 >= 15


def test_no_live_spec_can_buy_below_the_coverage_floor() -> None:
    """The coverage pass must evaluate everything a lab is allowed to buy, or a
    gated arm sits idle waiting for verdicts nobody is collecting.

    ANCHORED ON EVERY LIVE SPEC, NOT ON ONE LAB. This asserted equality with
    the Movers Lab's floor until 2026-09-10 and the Dex Lab's until 2026-09-13;
    each deletion orphaned it and needed a human to notice and re-point it at
    whatever was still alive. Asking the question of all of them instead
    survives the next deletion, and is the invariant that was actually meant.

    `LabService` reads `LIQUIDITY_FLOOR` off the spec and falls back to its own
    default, so a spec without one cannot buy thinner than the engine allows.
    """
    import types

    from app.lab import scheduler, service

    # The anchor: a spec that says nothing about liquidity buys at the engine's
    # default, so that default is what the coverage pass must reach.
    assert lab_coverage.MIN_LIQUIDITY_USD == int(service.DEFAULT_LIQUIDITY_FLOOR)

    # And the forward guard: no live spec may lower its own floor beneath it.
    # Vacuous today — with the Dex Lab deleted on 2026-09-13 no spec overrides
    # the default any more — and deliberately kept, because the next lab that
    # does is exactly the case this exists to catch.
    for module in list(vars(scheduler).values()):
        # MODULES only. SQLAlchemy's `func` answers `hasattr` for every name
        # there has ever been, so a bare duck-type check picks it up and then
        # fails on `int(<_FunctionGenerator>)`.
        if not isinstance(module, types.ModuleType):
            continue
        floor = getattr(module, "LIQUIDITY_FLOOR", None)
        if floor is None or not hasattr(module, "SPEC_VERSION"):
            continue
        assert int(floor) >= lab_coverage.MIN_LIQUIDITY_USD, (
            f"{module.SPEC_VERSION} may buy at {int(floor)}, below the "
            f"{lab_coverage.MIN_LIQUIDITY_USD} the coverage pass looks at")
