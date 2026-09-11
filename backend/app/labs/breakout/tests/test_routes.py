"""The read routes, against a seeded database.

These assert the SHAPES the frontend is built against. A field renamed here
without the fixture being renamed too is exactly the mismatch Phase 4's
definition of done forbids, so the names are checked explicitly rather than
by round-tripping a model.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.labs.breakout import api, config
from app.labs.breakout.models import (
    BoCandle,
    BoEpisode,
    BoLevels,
    BoSetupSnapshot,
    BoUniverseMember,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def member(mint="M1", symbol="AAA", volume=900_000) -> BoUniverseMember:
    return BoUniverseMember(
        mint=mint, symbol=symbol, name=f"Token {symbol}", pool_address=f"P{mint}",
        dex="raydium", pair_created_at=T0 - timedelta(days=90),
        liquidity_usd=Decimal("250000"), volume_24h_usd=Decimal(volume),
        price_usd=Decimal("50"), fdv=Decimal("1000000"), source="geckoterminal",
        first_seen=T0, last_seen=T0, active=True, fetch_failures=0,
    )


def snapshot(mint: str, state: str, score: int, bar: datetime) -> BoSetupSnapshot:
    return BoSetupSnapshot(
        mint=mint, bar_close_time=bar, state=state, score=score,
        components={"volume": 0.5, "structure": 1.0, "position": 0.9,
                    "compression": 0.3, "hourly": 0.8},
        price=Decimal("95"), resistance=Decimal("100"), distance_pct=Decimal("5"),
        hourly_missing=False, computed_at=bar,
    )


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("BREAKOUT_LAB_ENABLED", "true")


@pytest.fixture
def disabled(monkeypatch):
    monkeypatch.delenv("BREAKOUT_LAB_ENABLED", raising=False)


# --- the flag -------------------------------------------------------------------

async def test_every_route_answers_without_a_database_while_the_flag_is_off(
    disabled,
) -> None:
    """`None` as the session: if any of these touches it, this fails."""
    assert await api.setups(None, session=None) == []          # type: ignore[arg-type]
    assert await api.setup_detail("M1", session=None) == {"running": False}  # type: ignore[arg-type]
    assert (await api.episodes(session=None)).model_dump() == {  # type: ignore[arg-type]
        "total": 0, "items": []}
    assert await api.stats(session=None) == {"running": False}  # type: ignore[arg-type]


# --- /setups --------------------------------------------------------------------

@pytest.mark.integration
async def test_setups_puts_pre_breakout_first_then_orders_by_score(
    lab_session, enabled,
) -> None:
    bar = T0 + timedelta(hours=5)
    lab_session.add_all([member("A", "AAA"), member("B", "BBB"), member("C", "CCC")])
    lab_session.add_all([
        BoEpisode(mint="A", opened_at=T0), BoEpisode(mint="B", opened_at=T0),
        BoEpisode(mint="C", opened_at=T0),
    ])
    lab_session.add_all([
        snapshot("A", "WATCHING", 90, bar),        # high score, wrong state
        snapshot("B", "PRE_BREAKOUT", 66, bar),    # low score, right state
        snapshot("C", "WATCHING", 95, bar),
    ])
    await lab_session.flush()

    rows = await api.setups(None, session=lab_session)
    assert [r["symbol"] for r in rows] == ["BBB", "CCC", "AAA"]
    assert rows[0]["state"] == "PRE_BREAKOUT"


@pytest.mark.integration
async def test_a_setup_row_carries_every_field_the_watchlist_draws(
    lab_session, enabled,
) -> None:
    bar = T0 + timedelta(hours=5)
    lab_session.add(member("A", "AAA"))
    lab_session.add(BoEpisode(mint="A", opened_at=T0,
                              first_pre_breakout_at=T0 + timedelta(hours=1)))
    lab_session.add(snapshot("A", "PRE_BREAKOUT", 70, bar))
    await lab_session.flush()

    (row,) = await api.setups(None, session=lab_session)
    assert set(row) == {
        "mint", "symbol", "name", "pool", "state", "score", "components", "price",
        "resistance", "distance_pct", "opened_at", "first_pre_breakout_at",
        "hours_open", "liquidity_usd", "volume_24h_usd"}
    assert set(row["components"]) == {"volume", "structure", "position",
                                      "compression", "hourly"}
    assert row["hours_open"] > 0
    assert row["liquidity_usd"] == 250000.0


@pytest.mark.integration
async def test_setups_can_be_narrowed_to_one_state(lab_session, enabled) -> None:
    bar = T0 + timedelta(hours=5)
    lab_session.add_all([member("A", "AAA"), member("B", "BBB")])
    lab_session.add_all([BoEpisode(mint="A", opened_at=T0),
                         BoEpisode(mint="B", opened_at=T0)])
    lab_session.add_all([snapshot("A", "WATCHING", 60, bar),
                         snapshot("B", "PRE_BREAKOUT", 70, bar)])
    await lab_session.flush()
    rows = await api.setups("PRE_BREAKOUT", session=lab_session)
    assert [r["symbol"] for r in rows] == ["BBB"]


@pytest.mark.integration
async def test_a_closed_episode_is_not_on_the_watchlist(lab_session, enabled) -> None:
    lab_session.add(member("A", "AAA"))
    lab_session.add(BoEpisode(mint="A", opened_at=T0, closed_at=T0 + timedelta(hours=1),
                              close_reason="FAILED"))
    await lab_session.flush()
    assert await api.setups(None, session=lab_session) == []


# --- /setups/{mint} -------------------------------------------------------------

@pytest.mark.integration
async def test_the_token_panel_returns_levels_snapshot_episode_and_both_series(
    lab_session, enabled,
) -> None:
    bar = T0 + timedelta(hours=5)
    lab_session.add(member("A", "AAA"))
    lab_session.add(BoLevels(
        mint="A",
        clusters=[{"level": 100.0, "touches": 3, "first": T0.isoformat(),
                   "last": T0.isoformat(), "broken": False}],
        nearest_resistance=Decimal("100"), atr=Decimal("2"), close=Decimal("95"),
        daily_bars=30, computed_at=bar))
    lab_session.add(snapshot("A", "PRE_BREAKOUT", 70, bar))
    lab_session.add(BoEpisode(mint="A", opened_at=T0))
    for i in range(3):
        lab_session.add(BoCandle(
            mint="A", pool_address="PA", timeframe="day",
            open_time=T0 + timedelta(days=i), open=Decimal("9"), high=Decimal("11"),
            low=Decimal("8"), close=Decimal("10"), volume_usd=Decimal("500"),
            close_time=T0 + timedelta(days=i + 1)))
    await lab_session.flush()

    body = await api.setup_detail("A", session=lab_session)
    assert body["running"] is True
    assert body["token"]["symbol"] == "AAA"
    assert body["levels"]["nearest_resistance"] == 100.0
    assert body["levels"]["clusters"][0]["touches"] == 3
    assert body["latest_snapshot"]["state"] == "PRE_BREAKOUT"
    assert body["episode"]["close_reason"] is None
    assert set(body["candles"]) == {"day", "hour"}
    assert set(body["candles"]["day"][0]) == {"t", "o", "h", "l", "c", "v"}
    assert body["candles"]["hour"] == []


@pytest.mark.integration
async def test_the_token_panel_is_all_nulls_for_a_mint_it_never_saw(
    lab_session, enabled,
) -> None:
    body = await api.setup_detail("NOPE", session=lab_session)
    assert body["running"] is True
    assert body["token"] is None and body["levels"] is None
    assert body["latest_snapshot"] is None and body["episode"] is None
    assert body["candles"] == {"day": [], "hour": []}


# --- /episodes ------------------------------------------------------------------

@pytest.mark.integration
async def test_episodes_paginates_closed_episodes_newest_first(
    lab_session, enabled,
) -> None:
    lab_session.add(member("A", "AAA"))
    for i in range(5):
        lab_session.add(BoEpisode(
            mint="A", opened_at=T0 + timedelta(days=i),
            closed_at=T0 + timedelta(days=i, hours=2), close_reason="FAILED",
            entry_ref_price=Decimal("10"), trail25_result_pct=Decimal("-25"),
            outcome_at=T0 + timedelta(days=i + 4)))
    lab_session.add(BoEpisode(mint="A", opened_at=T0 + timedelta(days=9)))  # still open
    await lab_session.flush()

    page = await api.episodes(limit=2, offset=0, session=lab_session)
    assert page.total == 5, "the open one is not counted"
    assert len(page.items) == 2
    assert page.items[0].opened_at > page.items[1].opened_at
    assert page.items[0].symbol == "AAA"
    assert page.items[0].trail25_result_pct == -25.0

    second = await api.episodes(limit=2, offset=2, session=lab_session)
    assert {i.id for i in second.items}.isdisjoint({i.id for i in page.items})


@pytest.mark.integration
async def test_an_episode_row_carries_every_outcome_column(
    lab_session, enabled,
) -> None:
    lab_session.add(member("A", "AAA"))
    lab_session.add(BoEpisode(
        mint="A", opened_at=T0, first_pre_breakout_at=T0, closed_at=T0 + timedelta(hours=3),
        close_reason="BROKE_OUT", entry_ref_price=Decimal("10"),
        resistance_at_open=Decimal("12"), max_gain_pct_from_ref=Decimal("40"),
        max_loss_pct_from_ref=Decimal("-8"), pct_at_24h=Decimal("15"),
        pct_at_72h=Decimal("30"), trail25_result_pct=Decimal("22"),
        outcome_gappy=False, outcome_at=T0 + timedelta(days=4)))
    await lab_session.flush()

    (row,) = (await api.episodes(session=lab_session)).items
    assert set(row.model_dump()) == {
        "id", "mint", "symbol", "opened_at", "first_pre_breakout_at", "closed_at",
        "close_reason", "entry_ref_price", "resistance_at_open",
        "max_gain_pct_from_ref", "max_loss_pct_from_ref", "pct_at_24h", "pct_at_72h",
        "trail25_result_pct", "outcome_gappy"}
    assert row.pct_at_72h == 30.0


@pytest.mark.integration
async def test_the_episode_page_size_is_capped(lab_session, enabled) -> None:
    page = await api.episodes(limit=100_000, session=lab_session)
    assert page.total == 0  # and it did not try to build a million-row page


# --- /stats ---------------------------------------------------------------------

@pytest.mark.integration
async def test_stats_counts_open_by_state_and_closed_by_reason(
    lab_session, enabled,
) -> None:
    bar = T0 + timedelta(hours=5)
    lab_session.add_all([member("A", "AAA"), member("B", "BBB")])
    lab_session.add_all([BoEpisode(mint="A", opened_at=T0),
                         BoEpisode(mint="B", opened_at=T0)])
    lab_session.add_all([snapshot("A", "WATCHING", 60, bar),
                         snapshot("B", "PRE_BREAKOUT", 70, bar)])
    for reason in ("BROKE_OUT", "FAILED", "FAILED", "EXPIRED", "universe_exit"):
        lab_session.add(BoEpisode(mint="C", opened_at=T0,
                                  closed_at=T0 + timedelta(hours=1), close_reason=reason))
    await lab_session.flush()

    body = await api.stats(session=lab_session)
    assert body["open_by_state"] == {"PRE_BREAKOUT": 1, "WATCHING": 1}
    assert body["closed"] == {"n": 5, "broke_out": 1, "failed": 2, "expired": 2}


@pytest.mark.integration
async def test_stats_buckets_completed_outcomes_by_score_decile(
    lab_session, enabled,
) -> None:
    """The 'does the rule work' view. Two episodes scored 70 and one scored
    30; the deciles must not be pooled."""
    lab_session.add(member("A", "AAA"))
    await lab_session.flush()
    for i, (score, result) in enumerate([(70, 40.0), (75, 20.0), (30, -25.0)]):
        start = T0 + timedelta(days=i)
        lab_session.add(BoEpisode(
            mint="A", opened_at=start, first_pre_breakout_at=start,
            closed_at=start + timedelta(hours=2), close_reason="FAILED",
            entry_ref_price=Decimal("10"), trail25_result_pct=Decimal(str(result)),
            outcome_at=start + timedelta(days=4)))
        lab_session.add(snapshot("A", "PRE_BREAKOUT", score, start))
        await lab_session.flush()

    outcomes = (await api.stats(session=lab_session))["outcomes"]
    assert outcomes["n"] == 3
    assert outcomes["win_rate"] == pytest.approx(2 / 3, abs=1e-4), "rounded for JSON"
    deciles = {d["decile"]: d for d in outcomes["by_score_decile"]}
    assert set(deciles) == {3, 7}
    assert deciles[7]["n"] == 2 and deciles[7]["win_rate"] == 1.0
    assert deciles[3]["n"] == 1 and deciles[3]["win_rate"] == 0.0


@pytest.mark.integration
async def test_stats_is_honest_about_having_no_outcomes_yet(
    lab_session, enabled,
) -> None:
    """Nulls, not zeros. "No data" and "a mean of zero" are different claims."""
    outcomes = (await api.stats(session=lab_session))["outcomes"]
    assert outcomes == {"n": 0, "mean_trail25_pct": None, "median_trail25_pct": None,
                        "win_rate": None, "by_score_decile": []}


def test_the_state_order_the_watchlist_sorts_by_is_declared_once() -> None:
    """The frontend sorts the same way. One table, imported by both, or they
    will drift."""
    from app.labs.breakout.data import STATE_ORDER

    assert STATE_ORDER["PRE_BREAKOUT"] < STATE_ORDER["WATCHING"]
    assert set(STATE_ORDER) >= {"PRE_BREAKOUT", "WATCHING", "BROKE_OUT", "FAILED", "NONE"}
    assert config.PRE_SCORE > config.WATCH_SCORE
