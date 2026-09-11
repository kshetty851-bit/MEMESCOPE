"""The aggregation: what it counts, and what it refuses to count."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from app.labs.nse_breakout import states, stats


@dataclass
class E:
    """An episode as `stats` reads it."""

    opened: date = date(2025, 1, 1)
    max_score: int = 75
    breakout_date: date | None = date(2025, 1, 10)
    close_reason: str | None = None
    days_to_breakout: int | None = 9
    ret_ref_20: float | None = 5.0
    ret_bo_20: float | None = 3.0
    mfe_20: float | None = 9.0
    mae_20: float | None = -4.0
    mfe_bo_20: float | None = 7.0
    mae_bo_20: float | None = -2.0
    trail10_pct: float | None = 2.0
    trail10_stopped: bool | None = True
    rel_nifty_20: float | None = 1.0


def test_an_empty_record_reports_nothing_rather_than_zero() -> None:
    """Zero episodes with a 0% breakout rate reads as "none of them broke out",
    which is a finding. "We have no episodes" is not."""
    empty = stats.summarise([])
    assert empty["episodes"] == 0
    assert empty["reached_breakout_pct"] is None
    assert empty["by_score_decile"] == []


def test_the_breakout_rate_is_over_all_episodes() -> None:
    rows = [E(), E(breakout_date=None), E(breakout_date=None), E()]
    assert stats.summarise(rows)["reached_breakout_pct"] == pytest.approx(50.0)


def test_the_false_breakout_rate_is_over_the_ones_that_broke_out() -> None:
    """An episode that never broke out cannot have broken out falsely. Putting
    it in the denominator would make the rate look better the more setups
    fizzled before the level — the opposite of what it measures."""
    rows = [E(close_reason=states.FALSE_BREAKOUT), E(), E(breakout_date=None)]
    assert stats.summarise(rows)["false_breakout_pct"] == pytest.approx(50.0)


def test_a_missing_return_is_left_out_of_the_mean_not_counted_as_zero() -> None:
    """The one mistake that would quietly turn any result into a flat one."""
    rows = [E(ret_ref_20=10.0), E(ret_ref_20=None), E(ret_ref_20=20.0)]
    side = stats.summarise(rows)["from_ref"]
    assert side["n"] == 2
    assert side["mean_ret_20"] == pytest.approx(15.0)


def test_the_profit_factor_is_none_rather_than_infinity_with_no_losses() -> None:
    """A profit factor with no denominator is not a very good one, it is an
    unmeasured one — and infinity in a JSON payload is a rendering bug."""
    assert stats.summarise([E(trail10_pct=5.0)])["trail10"]["profit_factor"] is None
    mixed = stats.summarise([E(trail10_pct=6.0), E(trail10_pct=-3.0)])
    assert mixed["trail10"]["profit_factor"] == pytest.approx(2.0)


def test_deciles_bucket_on_the_peak_score_and_cover_one_to_ten() -> None:
    """On `max_score` — the highest the setup ever reached — not the score on
    the day it opened, which is whatever crossed the threshold first and is
    nearly the same number for every episode by construction."""
    rows = [E(max_score=s) for s in (5, 45, 62, 71, 88, 100)]
    deciles = {d["decile"] for d in stats.summarise(rows)["by_score_decile"]}
    assert deciles == {1, 5, 7, 8, 9, 10}
    assert stats._decile_of(100) == 10, "100 belongs in the top one"
    assert stats._decile_of(0) == 1


def test_the_decile_table_answers_the_question_it_exists_for() -> None:
    rows = [E(max_score=95, ret_bo_20=12.0)] * 3 + \
           [E(max_score=61, ret_bo_20=-1.0, breakout_date=None)] * 2
    table = {d["decile"]: d for d in stats.summarise(rows)["by_score_decile"]}
    assert table[10]["reached_breakout_pct"] == 100.0
    assert table[10]["mean_ret_bo_20"] == pytest.approx(12.0)
    assert table[7]["reached_breakout_pct"] == 0.0
    assert table[7]["mean_ret_bo_20"] is None, "nothing broke out to measure"


def test_by_year_splits_on_the_year_the_episode_opened() -> None:
    rows = [E(opened=date(2024, 6, 1)), E(opened=date(2025, 6, 1)),
            E(opened=date(2025, 7, 1))]
    years = {y["year"]: y["episodes"] for y in stats.summarise(rows)["by_year"]}
    assert years == {2024: 1, 2025: 2}


def test_the_thresholds_travel_with_the_numbers() -> None:
    """So a statistic can never be read against the wrong rules: the README's
    table and a later run are only comparable if this block matches."""
    snapshot = stats.config_snapshot()
    assert {"watch_score", "near_score", "break_vol_mult", "trail_pct"} <= \
        set(snapshot)
