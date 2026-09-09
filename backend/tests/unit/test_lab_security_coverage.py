"""The coverage pass must aim at coins that have NOT yet been judged.

It ran every minute, capped at 25, and still left 158 of 168 lab entries with
no evaluation on disk. The pass was working; it was pointed at the wrong end
of its own queue. `LOOKBACK` bounded `captured_at` — "has a recent deep print"
— which on 2026-09-09 selected 67 mints averaging 4.6 hours old and reaching
30, because a coin discovered yesterday and still trading prints every minute.
Ordered oldest-first, the cap was spent on coins judged hours earlier.

One assertion, on the query the function actually issues rather than on its
source text: the age bound is there, or the cap silently starves the labs
again and nothing in an equity curve says so.
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


def test_the_pass_bounds_how_OLD_a_candidate_may_BE() -> None:
    """Not just how recently it printed."""
    assert "discovered_tokens.discovered_at >=" in _sql()


def test_the_pass_still_requires_a_recent_print() -> None:
    """Both bounds, not one swapped for the other: a coin that stopped trading
    an hour ago is young and worthless to evaluate."""
    assert "token_market_snapshots.captured_at >=" in _sql()


def test_the_lookback_covers_the_checkpoint_with_room() -> None:
    """The labs judge at ten minutes. A lookback under that would drop coins
    before the decision that needs them."""
    assert lab_coverage.LOOKBACK.total_seconds() / 60 >= 15


def test_the_floor_matches_what_a_lab_can_buy() -> None:
    from app.movers import spec

    assert lab_coverage.MIN_LIQUIDITY_USD == int(spec.MIN_LIQUIDITY_USD)
