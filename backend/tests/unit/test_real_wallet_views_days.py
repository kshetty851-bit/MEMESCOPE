"""A wallet's profit per Dubai day (2026-09-30)."""

from datetime import UTC, datetime
from decimal import Decimal as D
from types import SimpleNamespace as P

from app.real_wallet.views import days_payload

NOW = datetime(2026, 9, 30, 18, 0, tzinfo=UTC)          # 30 Sep, 22:00 Dubai


def _pos(closed, net, status="CLOSED", gross=None):
    return P(status=status, closed_at=closed, realised_net_pnl_usd=net, realised_gross_pnl_usd=gross)


def test_closed_trades_add_up_per_dubai_day_newest_first_with_today_always_shown():
    days = days_payload([
        _pos(datetime(2026, 9, 29, 19, 30, tzinfo=UTC), D("1.20")),   # 29 Sep 23:30 Dubai
        _pos(datetime(2026, 9, 29, 20, 30, tzinfo=UTC), D("-0.50")),  # 30 Sep 00:30 Dubai
        _pos(datetime(2026, 9, 28, 10, 0, tzinfo=UTC), None, gross=D("2.00")),  # gross only
        _pos(None, None, status="OPEN"),                                # open: not counted
    ], NOW)
    assert [(d["day"], d["pnl_usd"], d["trades"], d["won"], d["running"]) for d in days] == [
        ("2026-09-30", "-0.50", 1, 0, True),
        ("2026-09-29", "1.20", 1, 1, False),
        ("2026-09-28", "2.00", 1, 1, False)]


def test_a_wallet_with_no_trades_still_shows_today():
    assert days_payload([], NOW) == [
        {"day": "2026-09-30", "running": True, "pnl_usd": "0.00", "trades": 0, "won": 0}]
