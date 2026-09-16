"""Rebooking closed trades under the 2026-09-16 exit and fee rules."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.labs.graduation import config
from app.labs.graduation.models import GradPaperPosition
from app.labs.graduation.restate import NOT_GRADUATION, restate_one
from app.labs.graduation.tournament import Mark, graduation_pool

pytestmark = pytest.mark.unit

D = Decimal
MINT = "21ExJ4jvmJopFCv2mf14LXtViJPFMVDVt2UXQ6PMpump"
OPENED = datetime(2026, 9, 14, 19, 9, 46, 625633, tzinfo=UTC)
DUE = OPENED + timedelta(minutes=5)
LAG = timedelta(seconds=config.FEED_LAG_S)


def _closed(**kw) -> GradPaperPosition:
    """FAIR on B3_198k_5m as it was booked: closed at 19:15:00 on a price from
    19:13, when the pool had been drained at 19:14:50."""
    fields = dict(
        id=uuid.uuid4(), book="B3_198k_5m", mint=MINT, opened_at=OPENED,
        open_quote=D("0.0004976"), open_fill=D("0.000500035066553"),
        notional_usd=D(100), sol_usd_at_open=D("103.195338"),
        notional_quote=D("0.969036027"), tokens=D("1937.936140519"),
        peak_quote=D("0.0005035"), last_quote=D("0.0005022"),
        liq_open_usd=D("609351.50"), liq_close_usd=D("613038.21"),
        closed_at=datetime(2026, 9, 14, 19, 15, 0, 146365, tzinfo=UTC),
        close_quote=D("0.0005022"), close_fill=D("0.00049974426160692"),
        close_reason="max_hold", pnl_quote=D("-0.000563565"),
        pnl_usd=D("-0.06"), net_return=D("-0.00058157"))
    fields.update(kw)
    return GradPaperPosition(**fields)


def _mark(ts: datetime, price: str, depth: str) -> Mark:
    return Mark(D(price), D(depth), ts, "dexscreener")


#: The two DexScreener rows either side of the drain, as recorded.
PRE = _mark(datetime(2026, 9, 14, 19, 14, 37, tzinfo=UTC), "0.0005035", "613852.52")
DRAINED = _mark(datetime(2026, 9, 14, 19, 16, 0, tzinfo=UTC), "1.747", "1829.22")


def test_a_token_that_never_graduated_is_excluded_and_left_as_it_was() -> None:
    position = _closed()
    audit = restate_one(position, pinned_pair="SomeRaydiumPool", marks=[PRE])
    assert position.excluded == NOT_GRADUATION
    assert audit.reason == NOT_GRADUATION
    # Nothing about the trade itself is rewritten: it is shown, never summed.
    assert position.pnl_usd == D("-0.06") == audit.was_pnl_usd
    assert position.close_quote == D("0.0005022")


def test_an_exit_booked_before_a_drain_is_rebooked_on_the_drain() -> None:
    position = _closed()
    audit = restate_one(position, pinned_pair=graduation_pool(MINT),
                        marks=[PRE, DRAINED])
    # Left out of every figure, as instructed — and still showing what it
    # really lost.
    assert position.excluded == "rugged"
    assert position.close_reason == audit.reason == "pool_collapsed"
    assert position.net_return < D("-0.99")
    assert position.pnl_usd < D("-99")
    # The close moves to when the book could first have known.
    assert position.closed_at == DRAINED.ts
    assert audit.exit_seen_at == DRAINED.ts - LAG
    # What it said before is kept.
    assert audit.was_pnl_usd == D("-0.06")
    assert audit.was_close_quote == D("0.0005022")
    assert audit.was_close_reason == "max_hold"
    assert audit.was_closed_at == datetime(2026, 9, 14, 19, 15, 0, 146365, tzinfo=UTC)
    assert position.pool_fee_bps == config.pool_fee_bps(D("0.0004976"))


def test_a_timed_exit_with_nothing_after_due_is_flagged_stale() -> None:
    position = _closed()
    audit = restate_one(position, pinned_pair=graduation_pool(MINT), marks=[PRE])
    assert position.excluded is None
    assert position.close_reason == audit.reason == "stale_exit"
    assert position.close_quote == PRE.price
    assert position.closed_at == datetime(2026, 9, 14, 19, 15, 0, 146365, tzinfo=UTC)


def test_a_stop_keeps_its_exit_and_is_only_recharged() -> None:
    """A stop fired on the mark in front of it. Only the fees change."""
    position = _closed(close_reason="hard_stop", close_quote=D("0.00044"))
    audit = restate_one(position, pinned_pair=graduation_pool(MINT),
                        marks=[PRE, DRAINED])
    assert audit.reason == "fees"
    assert position.close_reason == "hard_stop"
    assert position.close_quote == D("0.00044")
    # The pool's real tier and the router, both legs, where 25 bps was charged.
    assert D("-0.13") < position.net_return < D("-0.12")
