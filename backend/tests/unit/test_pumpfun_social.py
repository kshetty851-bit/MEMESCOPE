"""Comment activity — the first signal here that is not price or flow.

Eleven experiments varied price, liquidity, volume and wallet flow, and none
produced an edge. This collects something orthogonal. The tests are about the
two ways it could quietly become useless: storing the wrong quantity, and
storing it in the wrong units.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from app.pumpfun import social

pytestmark = pytest.mark.unit


def _row(**over):
    base = {
        "mint": "MINT1111111111111111111111111111111111111111",
        "reply_count": 120,
        "market_cap": 5_583_521.53,        # SOL-denominated
        "usd_market_cap": 576_442_762.0,   # USD
        "ath_market_cap": 576_442_762.28,  # USD
        "complete": True,
        "is_currently_live": False,
    }
    base.update(over)
    return base


def test_it_reads_the_USD_market_cap_not_the_quote_denominated_one() -> None:
    """The units trap, and it is not hypothetical — it produced a "1% of ATH"
    reading for coins that were sitting exactly AT their all-time high.

    `market_cap` is denominated in the quote asset (SOL); `ath_market_cap` is
    USD. Dividing one by the other is a unit error that looks like a finding.
    """
    r = social._reading(_row(), "last_reply")
    assert r is not None
    assert r.usd_market_cap == D("576442762.0")
    assert r.ath_market_cap == D("576442762.28")
    # The ratio the explore page's "movers" means: at its own peak.
    assert float(r.usd_market_cap / r.ath_market_cap) == pytest.approx(1.0, abs=1e-6)


def test_the_stored_quantity_is_the_raw_count_never_a_rate() -> None:
    """`reply_count` is CUMULATIVE, so it is a proxy for age as much as for
    interest. Velocity needs two readings and is derived at read time; a rate
    computed at write time would bake in whichever gap separated two polls."""
    r = social._reading(_row(reply_count=120), "last_reply")
    assert r.reply_count == 120
    assert not hasattr(r, "velocity")
    assert not hasattr(r, "replies_per_hour")


def test_the_listing_that_surfaced_a_coin_is_kept() -> None:
    """The sort IS the population — a coin under `last_reply` is being
    discussed, one under `market_cap` is merely large. Pooling them would
    merge two samples."""
    assert social._reading(_row(), "last_reply").source_sort == "last_reply"
    assert social._reading(_row(), "market_cap").source_sort == "market_cap"


def test_it_collects_last_reply_rather_than_reply_count() -> None:
    """Sorting by the cumulative count would select coins old enough to have
    accumulated comments — age wearing a signal's clothes, and the same
    selection error as ranking traders on a leaderboard's own window."""
    assert "last_reply" in social.SORTS
    assert "reply_count" not in social.SORTS


def test_a_row_without_a_mint_is_dropped_not_stored_blank() -> None:
    assert social._reading(_row(mint=None), "last_reply") is None
    assert social._reading({}, "last_reply") is None


def test_missing_numbers_stay_missing() -> None:
    """Null is not zero. A coin with no reply count has not been measured as
    silent, and storing 0 would make it look like the quietest coin there is."""
    r = social._reading(_row(reply_count=None, usd_market_cap=None), "last_reply")
    assert r.reply_count is None
    assert r.usd_market_cap is None


def test_every_row_in_a_poll_shares_one_timestamp() -> None:
    """The rate divides by the gap between polls. Per-row clocks would make
    that denominator differ by coin for no reason."""
    readings = [social._reading(_row(mint=f"M{i:043d}"), "last_reply") for i in range(4)]
    at = datetime(2026, 9, 8, 3, 0, tzinfo=UTC)
    rows = social.to_rows(readings, now=at)
    assert len(rows) == 4
    assert {r.observed_at for r in rows} == {at}


async def test_a_provider_failure_returns_nothing_and_never_raises(monkeypatch) -> None:
    """A third-party outage must not stop the beat that also settles the labs.
    A missed poll costs one gap in a rate; a raised exception costs the tick."""
    class _Boom:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): raise RuntimeError("provider down")

    monkeypatch.setattr(social.httpx, "AsyncClient", lambda **_k: _Boom())
    assert await social.fetch() == []


async def test_a_non_200_is_skipped_without_poisoning_the_batch(monkeypatch) -> None:
    class _Resp:
        status_code = 503
        @staticmethod
        def json(): return []

    class _C:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): return _Resp()

    monkeypatch.setattr(social.httpx, "AsyncClient", lambda **_k: _C())
    assert await social.fetch() == []


def test_the_table_has_retention_from_the_day_it_shipped() -> None:
    """`radar_rank_events` is why: it was the one table with no policy and
    reached 1.27M rows and 865MB before anyone noticed. At two listings every
    ten minutes this writes ~29k rows a day."""
    from app.core.config import settings
    from app.workers import retention_tasks

    assert hasattr(retention_tasks, "_prune_pumpfun_social")
    # Long enough to outlast the question: velocity against forward returns
    # needs weeks, so a 7-day window would delete the history first.
    assert settings.PUMPFUN_SOCIAL_RETENTION_DAYS >= 30
