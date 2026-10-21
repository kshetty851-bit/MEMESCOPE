"""The $10k book's 48-hour switch (2026-10-21): buy only after a profitable 48 hours."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.labs.graduation import pool_lab as pl

pytestmark = pytest.mark.unit
T0 = datetime(2026, 10, 10, tzinfo=UTC)


def row(hours: float, ret: float) -> SimpleNamespace:
    at = T0 + timedelta(hours=hours)
    return SimpleNamespace(opened_at=at, closed_at=at + timedelta(minutes=3), net_return=ret)


def test_it_stands_aside_after_a_losing_48_hours_and_returns_when_it_turns() -> None:
    losers = [row(h, -0.2) for h in range(6)]                 # -$60 over six trades
    late = row(10, 0.5)                                       # picked inside the losing window
    winners = [row(30 + h, 0.6) for h in range(6)]            # +$180 later
    after = row(40, 0.1)
    kept = pl.switched([*losers, late, *winners, after])
    assert late not in kept and after in kept
    assert all(r in kept for r in losers[:5])                 # too little history at first: it buys


def test_only_trades_closed_before_the_buy_count() -> None:
    rows = [row(h, 0.1) for h in range(5)]
    on, made, n = pl.green(rows, rows[-1].opened_at)          # the last one is still open then
    assert n == 4 and on                                      # under 5 closed: it buys
