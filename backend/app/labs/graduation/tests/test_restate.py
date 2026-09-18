"""Rebooking closed trades under the 2026-09-16 exit and fee rules."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.labs.graduation import config
from app.labs.graduation.models import GradPaperPosition
from app.labs.graduation.restate import BOOKS, NOT_GRADUATION, restate_one
from app.labs.graduation.tournament import ARMS, Mark, graduation_pool

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


def test_the_pre_registered_ab_is_never_restated() -> None:
    """Its judge weighs the trades its filter refused; leaving their rugs out
    would decide the verdict."""
    assert BOOKS == tuple(a.name for a in ARMS if not a.ab_experiment)
    assert "B3_198k_5m" in BOOKS
    assert not {"F01_all_2m", "F14_symnight_2m"} & set(BOOKS)


# --- onchain-2026-09-18 -----------------------------------------------------

BLUEY = "4qcmHsARuTi2ki1wcmNRdTmVqdUmN5LkU9DK4wsKpump"
BLUEY_AT = datetime(2026, 9, 17, 14, 24, 46, 300000, tzinfo=UTC)


def _reserves(sol: str, price: str) -> tuple[int, int]:
    """A pool holding `sol` SOL with its token at `price` SOL: raw units."""
    return int(D(sol) / D(price) * 10**6), int(D(sol) * 10**9)


def _held():
    from app.labs.graduation.held_watch import Held

    return Held(mint=BLUEY, pool="BlueyPool", base_vault="Vb", quote_vault="Vq",
                base_decimals=6, quote_decimals=9, quote_mint=config.WSOL_MINT)


def _bluey(**kw) -> GradPaperPosition:
    """Bluey on BASE_75k_5m as it was booked: bought at DexScreener's first
    report, 0.000004773, while the pool already traded near 0.0000541."""
    fields = {
        "id": uuid.uuid4(), "book": "BASE_75k_5m", "mint": BLUEY, "symbol": "Bluey",
        "opened_at": BLUEY_AT, "open_quote": D("0.000004773"), "open_fill": D("0.00000481"),
        "notional_usd": D(100), "sol_usd_at_open": D("100"), "notional_quote": D("1"),
        "tokens": D("207900.2079"), "peak_quote": D("0.0000563"),
        "last_quote": D("0.0000563"), "liq_open_usd": D("105824"),
        "liq_close_usd": D("198283"),
        "closed_at": BLUEY_AT + timedelta(minutes=5, seconds=11),
        "close_quote": D("0.0000563"), "close_fill": D("0.0000559"),
        "close_reason": "max_hold", "pnl_quote": D("10.4415"), "pnl_usd": D("1044.16"),
        "net_return": D("10.44157267")}
    fields.update(kw)
    return GradPaperPosition(**fields)


def test_a_stale_entry_is_rebooked_at_the_pools_own_price() -> None:
    from app.labs.graduation.restate import ONCHAIN, ONCHAIN_RULE, restate_one_onchain

    position = _bluey()
    audit = restate_one_onchain(position, held=_held(),
                                entry=_reserves("980", "0.0000541"),
                                exit=_reserves("1000", "0.0000563"), prior=None)
    assert audit is not None and (audit.rule, audit.reason) == (ONCHAIN_RULE, ONCHAIN)
    assert abs(position.open_quote / D("0.0000541") - 1) < D("0.001")
    # +4.1% on the pool, less the round trip: a small win, not +1,044%.
    assert D("0.01") < position.net_return < D("0.04")
    assert audit.was_net_return == D("10.44157267"), "the first booking is kept"
    assert position.excluded is None
    assert audit.exit_source == "chain"
    assert audit.exit_seen_at == BLUEY_AT + timedelta(minutes=5)


def test_a_trade_an_earlier_rule_restated_keeps_its_first_booking() -> None:
    from app.labs.graduation.models import GradPaperRestatement
    from app.labs.graduation.restate import ONCHAIN_RULE, restate_one_onchain

    position = _bluey(net_return=D("0.03"), pnl_usd=D("3.00"))
    prior = GradPaperRestatement(
        position_id=position.id, rule="exit-fees-2026-09-16", reason="fees",
        was_open_fill=D("0.0000048"), was_tokens=D("208333"), was_pnl_usd=D("1050.00"),
        was_net_return=D("10.5"))
    audit = restate_one_onchain(position, held=_held(),
                                entry=_reserves("980", "0.0000541"),
                                exit=_reserves("1000", "0.0000563"), prior=prior)
    assert audit is prior and audit.rule == ONCHAIN_RULE
    assert (audit.was_net_return, audit.was_pnl_usd) == (D("10.5"), D("1050.00"))


def test_a_drain_the_feed_missed_is_booked_and_counted() -> None:
    """HLDM: booked -2.5% on a stale exit; its pool had been drained to about
    a tenth of the entry price. Drains after 16 Sep count like any trade."""
    from app.labs.graduation.restate import ONCHAIN, restate_one_onchain

    position = _bluey(open_quote=D("0.0000541"), close_reason="stale_exit",
                      net_return=D("-0.025"), pnl_usd=D("-2.50"))
    audit = restate_one_onchain(position, held=_held(),
                                entry=_reserves("980", "0.0000541"),
                                exit=_reserves("30", "0.0000049"), prior=None)
    assert audit.reason == ONCHAIN
    assert position.net_return < D("-0.8")
    assert position.excluded is None, "a drain after 16 Sep is counted"


def test_a_trade_the_16_sep_what_if_left_out_stays_out() -> None:
    from app.labs.graduation.restate import RUGGED, restate_one_onchain

    position = _bluey(open_quote=D("0.0000541"), excluded=RUGGED)
    audit = restate_one_onchain(position, held=_held(),
                                entry=_reserves("980", "0.0000541"),
                                exit=_reserves("3", "0.0000001"), prior=None)
    assert position.excluded == RUGGED and audit.reason == "pool_collapsed"


def test_a_reading_that_cannot_be_priced_leaves_the_trade_as_booked() -> None:
    from app.labs.graduation.restate import restate_one_onchain

    position = _bluey()
    assert restate_one_onchain(position, held=_held(), entry=(0, 0),
                               exit=_reserves("1000", "0.0000563"), prior=None) is None
    assert position.net_return == D("10.44157267")
    assert position.open_quote == D("0.000004773")
