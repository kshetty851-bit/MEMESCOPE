"""USER1 sells like the Pump Catcher Lab; every other wallet keeps its hold."""
from decimal import Decimal

from app.lab.rules import MarkState
from app.labs.graduation import live_spec
from app.real_wallet import exit_driver as ed

Q50 = live_spec.BY_ID["G-Q50"].exits


def _at(minutes: float, multiple: str) -> MarkState:
    return MarkState(exec_multiple=Decimal(multiple), peak_exec_multiple=Decimal(multiple),
                     held_hours=minutes / 60, liquidity_usd=Decimal(60_000),
                     entry_liquidity_usd=Decimal(60_000), is_dead=False, sell_route_ok=None,
                     break_even_armed=False, partial_done=False)


def test_pump_wallet_sells_at_30pct_down_at_5m_else_10m():
    v = lambda m, x: ed.exit_verdict(ed.PUMP_EXITS, _at(m, x), pump=True)
    assert v(1, "1.26").action == "CLOSE"                        # x1.25 executable = the lab's +30%
    assert v(1, "1.24").action is None
    assert v(4.9, "0.80").action is None                         # before five: holds
    assert v(5.0, "0.99").reason == "down_at_5m"                 # down at five: out
    assert v(5.2, "1.05").action is None                         # up at five: stays
    assert v(7.0, "0.70").action is None                         # a later dip is not a second look
    assert v(10.0, "1.10").action == "CLOSE"                     # ten minutes: out


def test_other_wallets_keep_the_five_minute_hold():
    v = lambda m, x: ed.exit_verdict(Q50, _at(m, x), pump=False)
    assert v(1, "1.31").action is None and v(5.0, "1.31").action == "CLOSE"
    assert v(4.9, "0.80").action is None


def test_only_user1_is_on_the_pump_exit():
    assert ed.PUMP_EXIT_MEMBERS == frozenset({"USER1"})
    assert ed.pump_exit(None) is False


def test_user1_sells_on_the_freshest_price():
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace as N

    t = datetime(2026, 10, 27, tzinfo=UTC)
    snap = N(price_usd=Decimal("1.0"), captured_at=t)
    live = N(price_usd=Decimal("1.3"), captured_at=t + timedelta(seconds=15))
    assert ed.freshest(snap, live) is live                       # newer live mark wins
    assert ed.freshest(live, N(price_usd=Decimal("1"), captured_at=t)) is live
    assert ed.freshest(snap, None) is snap and ed.freshest(None, live) is live
    assert ed.freshest(snap, N(price_usd=None, captured_at=t + timedelta(seconds=9))) is snap
