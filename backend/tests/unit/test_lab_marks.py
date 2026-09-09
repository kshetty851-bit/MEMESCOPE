"""The mark must agree with the ledger about whether a coin is alive.

Two bugs, one week apart, both in the same column:

1. The view read `price_usd` off an INACTIVE snapshot. A dead pool reported
   0.0001867 against a real last trade of 0.00000366 — FIFTY-ONE TIMES higher
   — and a position correctly written off at zero displayed as +174%.
2. Fixed only by skipping inactive rows, it then returned the newest TRADING
   print however old. Three closed `dead_zero` positions showed +21.4%, +5.4%
   and +0.9%, each from a print that PREDATED its own close by 2-4 minutes,
   on the same row as an exit reason meaning "written off at zero".

The second is the interesting one: the first fix was correct and insufficient,
and nothing in an equity curve says so.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from app.lab import marks, service


def _sql() -> str:
    class _S:
        def __init__(self) -> None:
            self.statements: list[str] = []

        async def execute(self, statement, *a, **kw):
            self.statements.append(str(statement))
            return []

    s = _S()
    asyncio.run(marks.latest_trading_price(s, ["mint-a", "mint-b"]))
    return s.statements[0]


def test_the_mark_excludes_inactive_prints() -> None:
    assert "trading_status !=" in _sql()


def test_the_mark_rejects_a_print_the_pool_has_outlived() -> None:
    """The second bug. Skipping inactive rows leaves the last trading price
    standing for ever; a coin is only currently worth something if nothing has
    printed long after the print being quoted."""
    sql = _sql()
    assert "max(" in sql.lower(), "no newest-of-any-kind term"
    assert "captured_at <=" in sql or "captured_at) <=" in sql, \
        "no supersession bound on the quoted print"


def test_death_is_defined_once() -> None:
    """The engine closes the position and this module stops quoting a price.
    Same question, and it was answered by two constants until the trades view
    showed a dead coin at +5.4%."""
    assert service.DEATH_CONFIRMATION_WINDOW is marks.DEATH_CONFIRMATION_WINDOW


def test_the_window_is_a_duration_not_a_count() -> None:
    """"Two consecutive inactives" never confirms for a token that stops being
    polled at all — that is how the lab once froze its worst positions at their
    last healthy price and held them for ever."""
    assert isinstance(marks.DEATH_CONFIRMATION_WINDOW, timedelta)
    assert marks.DEATH_CONFIRMATION_WINDOW >= timedelta(minutes=1), \
        "shorter than a poll interval would call live coins dead"


def test_no_mints_asks_nothing() -> None:
    class _Explodes:
        async def execute(self, *a, **kw):
            raise AssertionError("queried the database for an empty set")

    assert asyncio.run(marks.latest_trading_price(_Explodes(), [])) == {}
    assert asyncio.run(marks.latest_trading_price(_Explodes(), [None, ""])) == {}
