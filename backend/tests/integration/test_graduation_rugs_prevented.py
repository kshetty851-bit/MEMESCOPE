"""The "rugs prevented" count (Karthik, 2026-10-02), against real rows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.labs.graduation import api
from app.labs.graduation.models import GradOperator, GradPaperPosition, GradToken

pytestmark = pytest.mark.integration

T0 = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def coin(mint, *, depth, why, end, minutes=0):
    """A coin bought at 1.0 that stood at `end` five minutes on."""
    at = T0 + timedelta(minutes=minutes)
    return GradOperator(
        mint=mint, pool=f"P{mint}", entry_at=at, price_native=Decimal(1),
        depth_usd=Decimal(depth), label_due_at=at + timedelta(minutes=5),
        rugged=Decimal(end) - 1 <= Decimal("-0.5"), exit_price_native=Decimal(end),
        blocked_reason=why)


def paper(book, mint, ret, minutes):
    at = T0 + timedelta(minutes=minutes)
    one, hundred = Decimal(1), Decimal(100)
    return GradPaperPosition(
        book=book, mint=mint, opened_at=at, open_quote=one, open_fill=one,
        notional_usd=hundred, sol_usd_at_open=hundred, notional_quote=one, tokens=one,
        peak_quote=one, closed_at=at + timedelta(minutes=5), net_return=Decimal(ret))


async def test_counts_the_rugs_it_refused_and_what_refusing_saved(db_session):
    db_session.add_all([
        coin("RugA", depth=90_000, why="linked_to_recent_rug", end="0.05", minutes=1),
        coin("RugB", depth=200_000, why="repeat_rug_operator", end="0.40", minutes=2),
        coin("WinC", depth=80_000, why="same_name_as_recent_rug", end="1.10", minutes=3),
        coin("RugD", depth=150_000, why=None, end="0.10", minutes=4),        # let through
        # Too shallow for the rule to have bought: not counted.
        coin("RugE", depth=40_000, why="known_rug_money", end="0.01", minutes=5),
        GradToken(mint="RugB", symbol="LATE", first_seen_at=T0),
        # The quiet rule: the baseline book had three rugs, the quiet one one.
        paper("BASE_75k_quiet_5m", "Q1", "-0.95", 0),
        paper("BASE_75k_5m", "B1", "-0.95", 1), paper("BASE_75k_5m", "B2", "-0.80", 2),
        paper("BASE_75k_5m", "B3", "-0.60", 3), paper("BASE_75k_5m", "B4", "0.02", 4),
    ])
    await db_session.flush()
    out = await api.rugs_prevented(db_session)
    assert (out["refused"], out["rugs_blocked"]) == (3, 2)
    # -95% -60% +10% at $50 a trade: the refused winner counts against it.
    assert out["saved_per_wallet_usd"] == "72.50"
    assert out["last_rug"]["symbol"] == "LATE"
    assert out["since"] == (T0 + timedelta(minutes=1)).isoformat()
    assert out["quiet_rugs_avoided"] == 2
