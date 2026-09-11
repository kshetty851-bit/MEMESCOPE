"""The five Phase 2 routes, against a seeded database.

These assert the SHAPES Phase 3 is built against. A field renamed here without
the fixture being renamed too is exactly the mismatch the Phase 3 definition of
done forbids, so the names are checked explicitly rather than by round-tripping
a model.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.labs.nse_breakout import api, states
from app.labs.nse_breakout.models import (
    BtCandle,
    BtEpisode,
    BtState,
    BtUniverseMember,
)

NOW = datetime(2026, 9, 11, 13, 0, tzinfo=UTC)
TODAY = datetime.now(UTC).date()


def member(symbol="AAA", *, active=True, name="Alpha Ltd") -> BtUniverseMember:
    return BtUniverseMember(
        symbol=symbol, name=name, isin=f"INE{symbol:0<6}01", series="EQ",
        last_close=Decimal("100"), turnover_20d=Decimal("500000000"), bars=300,
        first_seen=date(2024, 1, 1), last_seen=TODAY, active=active,
        updated_at=NOW)


def state(symbol="AAA", *, stage=states.NEAR, score=80) -> BtState:
    return BtState(
        symbol=symbol, bar_date=TODAY, state=stage, score=score,
        components={"proximity": 0.9, "compression": 0.5, "trend": 0.7,
                    "volume": 0.6, "touches": 0.66},
        close=Decimal("97"), resistance=Decimal("100"),
        distance_pct=Decimal("3.09"), range_pct=Decimal("8.0"), tightness=True,
        is_52w_high=True, week52_high=Decimal("100"), atr=Decimal("2.5"),
        volume_mult=Decimal("1.2"),
        clusters=[{"level": 100.0, "touches": 3, "first": "2025-01-01",
                   "last": "2025-06-01", "broken": False}],
        days_in_state=4, bars=300, updated_at=NOW)


def episode(symbol="AAA", *, source="live", broke=True, **kw) -> BtEpisode:
    values = {
        "symbol": symbol, "source": source, "opened": TODAY - timedelta(days=30),
        "first_near_date": TODAY - timedelta(days=30), "ref_price": Decimal("97"),
        "resistance": Decimal("100"), "score_at_open": 72, "max_score": 88,
        "state": states.BREAKOUT if broke else states.NEAR,
        "created_at": NOW,
    }
    if broke:
        values |= {"breakout_date": TODAY - timedelta(days=5),
                   "breakout_price": Decimal("102"),
                   "breakout_volume_mult": Decimal("1.8"), "days_to_breakout": 12,
                   "ret_bo_20": Decimal("6.5"), "mfe_bo_20": Decimal("11.0"),
                   "mae_bo_20": Decimal("-3.2"), "held_20d_pct": Decimal("6.5"),
                   "trail10_pct": Decimal("4.1"), "trail10_stopped": True}
    values |= {"ret_ref_20": Decimal("9.0"), "mfe_20": Decimal("13.0"),
               "mae_20": Decimal("-2.0"), "rel_nifty_20": Decimal("4.5")}
    return BtEpisode(**(values | kw))


# --- /near ------------------------------------------------------------------------

@pytest.mark.integration
async def test_near_puts_near_before_watch_then_orders_by_score(
    tracker_session, tracker_enabled,
) -> None:
    """The order the board is built against. Sorted in SQL, so a slice in the
    route cannot quietly change it."""
    tracker_session.add_all([
        member("AAA"), member("BBB"), member("CCC"),
        state("AAA", stage=states.WATCH, score=99),
        state("BBB", stage=states.NEAR, score=70),
        state("CCC", stage=states.NEAR, score=85),
    ])
    await tracker_session.flush()

    rows = await api.tracker_near(limit=200, session=tracker_session)
    assert [r["symbol"] for r in rows] == ["CCC", "BBB", "AAA"]
    assert [r["state"] for r in rows] == ["NEAR", "NEAR", "WATCH"]


@pytest.mark.integration
async def test_near_carries_every_field_the_board_draws(
    tracker_session, tracker_enabled,
) -> None:
    tracker_session.add_all([member(), state()])
    await tracker_session.flush()
    row = (await api.tracker_near(limit=200, session=tracker_session))[0]
    assert set(row) == {"symbol", "name", "state", "score", "close", "resistance",
                        "distance_pct", "tightness", "is_52w_high",
                        "days_in_state", "turnover_20d", "bar_date"}
    assert row["name"] == "Alpha Ltd" and row["days_in_state"] == 4
    assert "sector" not in row, "no keyless source; omitted rather than faked"


@pytest.mark.integration
async def test_a_name_that_left_the_universe_leaves_the_board(
    tracker_session, tracker_enabled,
) -> None:
    """Its last state row survives — that is the record — but an inactive name
    must not sit on the board for ever."""
    tracker_session.add_all([member("GONE", active=False), state("GONE")])
    await tracker_session.flush()
    assert await api.tracker_near(limit=200, session=tracker_session) == []


# --- /breakouts --------------------------------------------------------------------

@pytest.mark.integration
async def test_breakouts_returns_recent_ones_with_the_move_since(
    tracker_session, tracker_enabled,
) -> None:
    tracker_session.add_all([member(), state(), episode()])
    await tracker_session.flush()
    rows = await api.tracker_breakouts(days=30, source="live", session=tracker_session)
    assert len(rows) == 1
    row = rows[0]
    assert row["symbol"] == "AAA"
    assert row["breakout_price"] == 102.0
    assert row["volume_mult"] == pytest.approx(1.8)
    # Against the latest stored close (97), so it moves with the data.
    assert row["ret_since_pct"] == pytest.approx((97 - 102) / 102 * 100, abs=1e-3)
    assert row["max_gain_pct"] == 11.0 and row["max_drawdown_pct"] == -3.2
    assert row["days_since"] == 5 and row["false_breakout"] is False


@pytest.mark.integration
async def test_breakouts_respects_the_window_and_the_source(
    tracker_session, tracker_enabled,
) -> None:
    tracker_session.add_all([
        member(), state(),
        episode(breakout_date=TODAY - timedelta(days=200)),
        episode("BBB", source="replay"),
    ])
    tracker_session.add(member("BBB"))
    await tracker_session.flush()
    assert await api.tracker_breakouts(days=30, source="live", session=tracker_session) == []
    old = await api.tracker_breakouts(days=365, source="live", session=tracker_session)
    assert [r["symbol"] for r in old] == ["AAA"]
    replayed = await api.tracker_breakouts(days=30, source="replay",
                                           session=tracker_session)
    assert [r["symbol"] for r in replayed] == ["BBB"]


# --- /stock/{symbol} ---------------------------------------------------------------

@pytest.mark.integration
async def test_stock_returns_levels_score_episode_history_and_candles(
    tracker_session, tracker_enabled,
) -> None:
    tracker_session.add_all([member(), state(), episode(closed=None)])
    tracker_session.add_all([
        BtCandle(symbol="AAA", date=TODAY - timedelta(days=i),
                 open=Decimal("96"), high=Decimal("99"), low=Decimal("95"),
                 close=Decimal("97"), volume=1000, turnover=Decimal("97000"),
                 adjusted=False, suspect_gap=False)
        for i in range(5)])
    await tracker_session.flush()

    payload = await api.tracker_stock("aaa", candles=750, session=tracker_session)
    assert set(payload) == {"stock", "levels", "score", "episode", "history",
                            "candles"}
    assert payload["stock"]["name"] == "Alpha Ltd"
    assert payload["levels"]["clusters"][0]["level"] == 100.0
    assert payload["levels"]["is_52w_high"] is True
    assert payload["score"]["score"] == 80
    assert set(payload["score"]["components"]) == {
        "proximity", "compression", "trend", "volume", "touches"}
    assert payload["episode"]["breakout_price"] == 102.0
    assert len(payload["history"]) == 1
    assert [c["d"] for c in payload["candles"]] == sorted(
        c["d"] for c in payload["candles"]), "oldest first, as a chart draws"
    assert set(payload["candles"][0]) == {"d", "o", "h", "l", "c", "v", "suspect"}


@pytest.mark.integration
async def test_an_unknown_symbol_is_a_404(tracker_session, tracker_enabled) -> None:
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as raised:
        await api.tracker_stock("NOPE", candles=750, session=tracker_session)
    assert raised.value.status_code == 404


@pytest.mark.integration
async def test_a_symbol_with_no_state_yet_is_not_an_error(
    tracker_session, tracker_enabled,
) -> None:
    """A name in the universe that the detection pass has not reached has no
    levels and no score. That is a fact, not a 500."""
    tracker_session.add(member("NEW"))
    await tracker_session.flush()
    payload = await api.tracker_stock("NEW", candles=750, session=tracker_session)
    assert payload["levels"] is None and payload["score"] is None
    assert payload["episode"] is None and payload["history"] == []


# --- /episodes and /stats -----------------------------------------------------------

@pytest.mark.integration
async def test_episodes_paginate_within_one_source(
    tracker_session, tracker_enabled,
) -> None:
    tracker_session.add_all([
        episode(f"S{i}", source="replay", opened=date(2025, 1, 1) + timedelta(days=i),
                id=uuid.uuid4()) for i in range(5)])
    tracker_session.add(episode("LIVE1", source="live"))
    await tracker_session.flush()

    page = await api.tracker_episodes(source="replay", limit=2, offset=0,
                                      session=tracker_session)
    assert page["total"] == 5 and len(page["items"]) == 2
    assert all(i["source"] == "replay" for i in page["items"])
    second = await api.tracker_episodes(source="replay", limit=2, offset=2,
                                        session=tracker_session)
    assert {i["id"] for i in page["items"]} & {i["id"] for i in second["items"]} \
        == set()


@pytest.mark.integration
async def test_stats_reports_the_rates_and_the_rules_they_came_from(
    tracker_session, tracker_enabled,
) -> None:
    tracker_session.add_all([
        episode("A", source="replay", broke=True),
        episode("B", source="replay", broke=False),
        episode("C", source="replay", broke=True,
                close_reason=states.FALSE_BREAKOUT),
    ])
    await tracker_session.flush()

    payload = await api.tracker_stats(source="replay", session=tracker_session)
    assert payload["episodes"] == 3
    assert payload["reached_breakout_pct"] == pytest.approx(66.67, abs=0.01)
    # Of the ones that BROKE OUT: an episode that never broke out cannot have
    # broken out falsely.
    assert payload["false_breakout_pct"] == pytest.approx(50.0)
    assert payload["from_ref"]["mean_ret_20"] == pytest.approx(9.0)
    assert payload["from_breakout"]["n"] == 2
    assert payload["config"]["near_score"] and payload["config"]["trail_pct"]
    assert any("survivorship" in c for c in payload["caveats"])


@pytest.mark.integration
async def test_every_route_is_quiet_while_the_flag_is_off(
    tracker_session, monkeypatch,
) -> None:
    """Off, the routes answer empty rather than reaching for tables that may
    not exist. `/stock` is the exception: a 503 says "not running", where an
    empty body would read as "no such stock"."""
    from fastapi import HTTPException
    monkeypatch.setenv("NSE_BREAKOUT_ENABLED", "false")
    assert await api.tracker_near(limit=200, session=tracker_session) == []
    assert await api.tracker_breakouts(days=30, source="live", session=tracker_session) == []
    page = await api.tracker_episodes(source="replay", limit=100, offset=0,
                                      session=tracker_session)
    assert page["items"] == []
    assert (await api.tracker_stats(source="replay", session=tracker_session))["episodes"] == 0
    with pytest.raises(HTTPException) as raised:
        await api.tracker_stock("AAA", candles=750, session=tracker_session)
    assert raised.value.status_code == 503
