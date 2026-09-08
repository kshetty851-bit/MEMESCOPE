"""The graduation collector: our stamp is the measurement.

pump.fun exposes `complete` but no graduation timestamp. Everything that
matters here follows from that: the first sighting IS the event time, so the
tests defend what would corrupt it — stamping a coin that graduated before we
looked, re-stamping one we already have, and storing an implausible market cap
as though it were a reading.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from app.models.graduation import PumpfunGraduation, PumpfunGraduationMark
from app.pumpfun import graduation

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


def _coin(mint: str, *, age_min: float, mcap=50000.0, ath=60000.0):
    created = NOW - timedelta(minutes=age_min)
    return {"mint": mint, "complete": True,
            "created_timestamp": int(created.timestamp() * 1000),
            "usd_market_cap": mcap, "ath_market_cap": ath, "reply_count": 3}


async def _run_discover(db_session, monkeypatch, coins):
    async def fake_get(client, url, **params):
        return coins
    monkeypatch.setattr(graduation, "_get", fake_get)
    return await graduation.discover(db_session, now=NOW)


# --------------------------------------------------------------------------
# the stamp
# --------------------------------------------------------------------------


async def test_a_fresh_graduate_is_stamped_at_first_sighting(db_session, monkeypatch):
    out = await _run_discover(db_session, monkeypatch,
                              [_coin("Mint" + "a" * 40, age_min=20)])
    assert out["stamped"] == 1
    g = (await db_session.execute(select(PumpfunGraduation))).scalars().first()
    assert g.first_seen_complete_at == NOW
    assert g.mcap_usd_at_graduation == D("50000")


async def test_a_coin_that_graduated_before_we_looked_is_refused(db_session, monkeypatch):
    """THE test. A coin that graduated last week still reads `complete`, and
    stamping it today would record a fact about US — when we noticed — as
    though it were a fact about the coin. That single error is what made the
    snapshot analysis unanswerable, because every bucket then mixes coins that
    graduated minutes ago with coins that graduated days ago."""
    out = await _run_discover(
        db_session, monkeypatch,
        [_coin("Old" + "b" * 41,
               age_min=graduation.MAX_AGE_AT_DISCOVERY_MINUTES + 60)])
    assert out["stamped"] == 0 and out["too_old"] == 1
    assert (await db_session.execute(select(PumpfunGraduation))).first() is None


async def test_a_coin_is_never_stamped_twice(db_session, monkeypatch):
    """The stamp is the FIRST sighting. A second one would overwrite the only
    thing this table exists to record."""
    coins = [_coin("Mint" + "c" * 40, age_min=10)]
    first = await _run_discover(db_session, monkeypatch, coins)
    second = await _run_discover(db_session, monkeypatch, coins)
    assert first["stamped"] == 1
    assert second["stamped"] == 0 and second["already_known"] == 1
    rows = (await db_session.execute(select(PumpfunGraduation))).scalars().all()
    assert len(rows) == 1 and rows[0].first_seen_complete_at == NOW


async def test_an_implausible_market_cap_is_unknown_not_stored(db_session, monkeypatch):
    """pump.fun has returned caps above 10^20. Storing one — or clamping it —
    puts a number in the table that somebody later trusts. None says we do not
    know, which is true."""
    out = await _run_discover(db_session, monkeypatch,
                              [_coin("Mint" + "d" * 40, age_min=5, mcap=1e25)])
    assert out["stamped"] == 1
    g = (await db_session.execute(select(PumpfunGraduation))).scalars().first()
    assert g.mcap_usd_at_graduation is None


# --------------------------------------------------------------------------
# the follow-up marks
# --------------------------------------------------------------------------


async def _stamp(db_session, mint: str, ago_min: float):
    g = PumpfunGraduation(mint_address=mint,
                          first_seen_complete_at=NOW - timedelta(minutes=ago_min),
                          created_at_source=NOW - timedelta(minutes=ago_min + 5),
                          mcap_usd_at_graduation=D("50000"))
    db_session.add(g)
    await db_session.flush()
    return g


async def test_a_mark_is_taken_at_the_target_age(db_session, monkeypatch):
    await _stamp(db_session, "Mint" + "e" * 40, ago_min=5)

    async def fake_get(client, url, **params):
        return {"usd_market_cap": 25000.0, "ath_market_cap": 70000.0}
    monkeypatch.setattr(graduation, "_get", fake_get)

    out = await graduation.mark(db_session, now=NOW)
    assert out["written"] == 1
    m = (await db_session.execute(select(PumpfunGraduationMark))).scalars().first()
    assert m.minutes_since == 5 and m.mcap_usd == D("25000")


async def test_a_mark_is_never_written_twice_for_the_same_age(db_session, monkeypatch):
    """`mark` runs every minute and the tolerance window is wider than the poll
    interval, so the same coin is due repeatedly. Without the guard the cohort
    would be counted several times at one age."""
    await _stamp(db_session, "Mint" + "f" * 40, ago_min=5)

    async def fake_get(client, url, **params):
        return {"usd_market_cap": 25000.0, "ath_market_cap": 70000.0}
    monkeypatch.setattr(graduation, "_get", fake_get)

    await graduation.mark(db_session, now=NOW)
    await graduation.mark(db_session, now=NOW + timedelta(minutes=1))
    rows = (await db_session.execute(
        select(PumpfunGraduationMark).where(
            PumpfunGraduationMark.minutes_since == 5))).scalars().all()
    assert len(rows) == 1


async def test_a_coin_too_young_for_a_target_is_not_marked(db_session, monkeypatch):
    await _stamp(db_session, "Mint" + "g" * 40, ago_min=1)

    async def fake_get(client, url, **params):
        return {"usd_market_cap": 1.0}
    monkeypatch.setattr(graduation, "_get", fake_get)

    out = await graduation.mark(db_session, now=NOW)
    assert out["written"] == 0


async def test_an_unreadable_response_writes_no_row(db_session, monkeypatch):
    """A missing reading must be an ABSENT row, not a row of nulls — the two
    read identically in an average and only one of them is honest."""
    await _stamp(db_session, "Mint" + "h" * 40, ago_min=5)

    async def fake_get(client, url, **params):
        return None
    monkeypatch.setattr(graduation, "_get", fake_get)

    out = await graduation.mark(db_session, now=NOW)
    assert out["written"] == 0 and out["unreadable"] == 1
    assert (await db_session.execute(select(PumpfunGraduationMark))).first() is None


def test_the_targets_cover_the_question_being_asked():
    """The question is what the FIRST HOUR does, so the early targets are dense
    and 60 is the boundary of the claim."""
    assert graduation.TARGET_MINUTES == (5, 15, 30, 60)
    assert graduation.MARK_TOLERANCE_MINUTES > 1, "wider than the poll interval"
