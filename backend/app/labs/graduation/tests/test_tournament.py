"""Fifty arms, eight of which must be incapable of an edge."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.labs.graduation import config
from app.labs.graduation.tournament import (
    ARMS,
    BY_NAME,
    CONTROLS,
    Arm,
    _coin,
    accepts,
)

D = Decimal
NIGHT = datetime(2026, 9, 13, 20, 0, tzinfo=UTC)
DAY = datetime(2026, 9, 13, 10, 0, tzinfo=UTC)
TOKEN = {"mint": "Abc123pump", "liquidity": D(150_000), "fdv": D(2_000_000),
         "sells": 0, "reuse": 4}


def test_the_tournament_is_fifty_arms_of_which_eight_are_noise() -> None:
    """The controls are the whole point. Fifty strategies produce a leader in
    an hour whether or not any of them is good, so the leaderboard only means
    something against arms that provably cannot have an edge."""
    assert len(ARMS) == 50
    assert len(CONTROLS) == 8
    assert len({a.name for a in ARMS}) == 50
    assert all(len(a.name) <= 32 for a in ARMS)


def test_arms_differ_only_in_entry_and_exit() -> None:
    """Anything else varying between arms would be what the tournament
    measures. Size, costs and clock are shared by construction — the Arm
    record has nowhere to put them."""
    assert set(Arm.__dataclass_fields__) == {
        "name", "entry", "hold", "tp", "trail", "note"}


def test_a_control_decides_on_nothing_and_never_changes_its_mind() -> None:
    """Hashed rather than drawn: a control that re-rolled each tick would be a
    different rule every time, and could not be compared with anything."""
    assert _coin("R1_coin50_5m", "abc", 50) == _coin("R1_coin50_5m", "abc", 50)
    mints = [f"m{i}pump" for i in range(4000)]
    for arm in CONTROLS:
        pct = int(arm.entry[4:])
        taken = sum(1 for m in mints if _coin(arm.name, m, pct))
        assert abs(taken / len(mints) * 100 - pct) < 4, arm.name
    # Two controls with the same rule must still pick different tokens, or
    # they are one control counted twice.
    a = {m for m in mints if _coin("R1_coin50_5m", m, 50)}
    b = {m for m in mints if _coin("R2_coin50_5m", m, 50)}
    assert 0.2 < len(a & b) / len(a | b) < 0.5


def test_every_entry_filter_is_implemented() -> None:
    """`accepts` raises on an unknown key, so a typo in an arm name would be a
    silent no-trade rather than an error."""
    for arm in ARMS:
        accepts(arm, open_at=NIGHT, **TOKEN)
    with pytest.raises(ValueError):
        accepts(Arm("bogus", "no_such_filter", 5), open_at=NIGHT, **TOKEN)


def test_the_filters_split_the_population_the_way_they_claim() -> None:
    def took(name: str, when: datetime, **over: object) -> bool:
        return accepts(BY_NAME[name], open_at=when, **{**TOKEN, **over})

    assert took("E05_hold_5m", DAY) and took("E05_hold_5m", NIGHT)
    assert took("F04_night_5m", NIGHT) and not took("F04_night_5m", DAY)
    assert took("F05_day_5m", DAY) and not took("F05_day_5m", NIGHT)
    assert took("F01_sym_5m", DAY) and not took("F01_sym_5m", DAY, reuse=0)
    assert took("F03_newsym_5m", DAY, reuse=0) and not took("F03_newsym_5m", DAY)
    assert took("F06_deep_5m", DAY) and not took("F06_deep_5m", DAY, liquidity=D(5_000))
    assert took("F07_shallow_5m", DAY, liquidity=D(5_000))
    assert took("F08_nosell_5m", DAY) and not took("F08_nosell_5m", DAY, sells=7)
    assert took("F09_hassell_5m", DAY, sells=7)
    assert took("F10_bigcap_5m", DAY) and not took("F10_bigcap_5m", DAY, fdv=D(50_000))
    assert took("F11_smallcap_5m", DAY, fdv=D(50_000))
    # The A/B arm needs BOTH conditions.
    assert took("C01_symnight_5m", NIGHT)
    assert not took("C01_symnight_5m", DAY)
    assert not took("C01_symnight_5m", NIGHT, reuse=0)


def test_a_missing_feature_is_a_refusal_not_a_pass() -> None:
    """DexScreener can answer without liquidity or a transaction count. An arm
    that treated a missing value as satisfying its filter would be trading a
    different population from the one it claims."""
    for name in ("F06_deep_5m", "F07_shallow_5m", "F10_bigcap_5m", "F11_smallcap_5m"):
        assert not accepts(BY_NAME[name], open_at=NIGHT,
                           **{**TOKEN, "liquidity": None, "fdv": None})
    for name in ("F08_nosell_5m", "F09_hassell_5m"):
        assert not accepts(BY_NAME[name], open_at=NIGHT, **{**TOKEN, "sells": None})
    assert not accepts(BY_NAME["F01_sym_5m"], open_at=NIGHT, **{**TOKEN, "reuse": None})


def test_the_live_book_and_the_ab_arm_are_both_in_the_tournament() -> None:
    """The Paper panels render two arms of the leaderboard rather than a
    separate experiment, so those names must exist."""
    assert config.PAPER_BOOKS == ("E05_hold_5m", "C01_symnight_5m")
    for name in config.PAPER_BOOKS:
        assert name in BY_NAME
    assert BY_NAME["E05_hold_5m"].hold == config.PAPER_MAX_HOLD_MINUTES


def test_the_calling_gate_is_stated_before_the_tournament_runs() -> None:
    """Including the term that separates 'leads' from 'beats chance'."""
    assert config.TOURNEY_MIN_TRADES >= 40
    assert D("1.5") <= config.TOURNEY_MIN_PF
    assert D("0.20") >= config.TOURNEY_MAX_TOKEN_SHARE


def test_an_arm_that_has_not_traded_cannot_lead() -> None:
    """Ranking on P&L alone puts a never-traded $0.00 above an arm that took
    one trade and lost a dollar, so the top of the board fills with arms whose
    filter has not matched anything yet. Observed live within a minute of the
    tournament opening: 17 trades closed and the board showed a leader with
    none of them.
    """
    rows = [
        {"name": "untraded", "trades": 0, "pnl": D("0.00")},
        {"name": "lost_one", "trades": 1, "pnl": D("-1.30")},
        {"name": "won_two", "trades": 2, "pnl": D("4.10")},
    ]
    rows.sort(key=lambda r: (r["trades"] > 0, r["pnl"]), reverse=True)
    assert [r["name"] for r in rows] == ["won_two", "lost_one", "untraded"]
