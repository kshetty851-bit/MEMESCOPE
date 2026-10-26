"""Fresh Catch Lab: who qualifies, how a trade is priced, how the $1,000 book walks."""
from datetime import UTC, datetime, timedelta

from app.labs.graduation import fresh_catch as fc

G = datetime(2026, 10, 26, 4, tzinfo=UTC)            # 08:00 Dubai is 04:00 UTC


def test_qualifies(monkeypatch):
    monkeypatch.setattr(fc, "derive_or_none", lambda m, pumpfun_program: ("POOL", 0))
    ok = (G + timedelta(seconds=20), "POOL", 1.0, 15_000, 13, 7)
    noon = G + timedelta(hours=6)
    assert fc.qualifies((noon + timedelta(seconds=20), *ok[1:]), noon, "M") is None
    assert fc.qualifies(ok, G, "M") == "morning"                                  # 08:00 Dubai
    assert fc.qualifies((noon + timedelta(seconds=40), *ok[1:]), noon, "M") == "not_fresh"
    assert fc.qualifies((noon, "POOL", 1.0, 31_000, 13, 7), noon, "M") == "pool"
    assert fc.qualifies((noon, "POOL", 1.0, 15_000, 12, 7), noon, "M") == "buys_under_65"
    assert fc.qualifies((noon, "OTHER", 1.0, 15_000, 13, 7), noon, "M") == "not_sol_pool"


def test_priced_buys_the_next_reading_and_sells_four_minutes_later():
    t = G
    after = [(t + timedelta(seconds=20), "dexscreener", 1.0, 20_000),
             (t + timedelta(seconds=200), "dexscreener", 1.5, 20_000),
             (t + timedelta(seconds=270), "dexscreener", 1.2, 20_000)]
    p = fc.priced(after)
    assert p["how"] == "dex" and abs(p["gross"] - 0.2) < 1e-9
    assert p["net"] < p["gross"]                                                  # fees + impact
    assert fc.priced(after[:1])["how"] == "unpriced" and fc.priced(after[:1])["net"] == -1.0


def test_book_needs_free_cash_and_counts_rugs():
    def r(i, net):
        e = G + timedelta(minutes=10 * i)
        return {"why": None, "symbol": "X", "pool": 15_000, "seen_s": 20, "buys": 9, "sells": 1,
                "entry_at": e.isoformat(), "exit_at": (e + timedelta(minutes=4)).isoformat(), "net": net, "how": "dex"}
    b = fc.book({"A": r(0, 1.0), "B": r(1, -0.9), "C": {"why": "pool"}}, G)
    assert b["trades"] == 2 and b["rugs"] == 1 and b["pnl_usd"] == 5.0 and b["refused"] == {"pool": 1}
