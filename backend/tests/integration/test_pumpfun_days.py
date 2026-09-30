"""Karthik's Lab: money flowing into pump.fun, one Dubai day at a time."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.labs.graduation import api
from app.labs.graduation.models import GradMigration, GradPostgradSample, GradToken

pytestmark = pytest.mark.integration

# 24 Sep 2026, 10:00 Dubai.
DAY = datetime(2026, 9, 24, 6, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    monkeypatch.setattr(api, "_PUMPFUN_DAYS", {})
    monkeypatch.setattr(api, "_PUMPFUN_TODAY", None)


async def test_each_dubai_day_counts_launches_graduations_and_new_pool_money(db_session):
    db_session.add_all([
        GradToken(mint=f"L{i}", first_seen_at=DAY + timedelta(minutes=i)) for i in range(3)])
    # 23:59 Dubai on the 24th and 00:01 Dubai on the 25th: different days.
    db_session.add_all([
        GradToken(mint="late", first_seen_at=datetime(2026, 9, 24, 19, 59, tzinfo=UTC)),
        GradToken(mint="next", first_seen_at=datetime(2026, 9, 24, 20, 1, tzinfo=UTC)),
    ])
    for mint, liq in (("DEEP", 120_000), ("THIN", 30_000)):
        db_session.add(GradMigration(mint=mint, ts=DAY))
        db_session.add(GradPostgradSample(ts=DAY + timedelta(seconds=40), mint=mint,
                                          source="dexscreener", liquidity_usd=Decimal(liq),
                                          price_usd=Decimal("0.01"), price_native=Decimal("0.0001")))
        # A reading after the two minutes does not count.
        db_session.add(GradPostgradSample(ts=DAY + timedelta(minutes=5), mint=mint,
                                          source="dexscreener", liquidity_usd=Decimal(999_999)))
    await db_session.flush()

    out = await api.pumpfun_days(db_session)
    days = {d["day"]: d for d in out["days"]}
    d24 = days["2026-09-24"]
    assert (d24["launches"], d24["graduations"], d24["pools_75k"]) == (4, 2, 1)
    assert d24["pools_usd"] == "150000"
    # No book trade that day: priced at the latest SOL rate, 0.01 / 0.0001 = $100.
    assert d24["into_curves_usd"] == str(2 * api.GRADUATION_SOL * 100)
    assert days["2026-09-25"]["launches"] == 1
    assert out["days"][0]["running"] is True and out["days"][-1]["day"] == "2026-09-23"
