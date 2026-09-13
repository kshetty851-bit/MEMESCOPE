"""The replay's bookkeeping: attribution, drawdown, and the gate.

These are not strategy tests — `test_engine.py` is that. These check the
arithmetic that turns a trade list into the numbers the report is judged on,
because a gate applied to a misattributed year is a gate that measured nothing.
"""

from __future__ import annotations

import array
from datetime import UTC, datetime, timedelta

import pytest

from app.labs.forex_lab import config
from app.labs.forex_lab.backtest import _max_drawdown, _profit_factor, replay
from app.labs.forex_lab.engine import GridConfig, Trade

PIP = 0.0001


def series(start: datetime, prices) -> tuple[array.array, array.array]:
    """One candle a minute, no wick, walking through `prices`."""
    ts, px = array.array("q"), array.array("f")
    t = start
    prev = prices[0]
    for p in prices:
        ts.append(int(t.timestamp()))
        px.extend((prev, max(prev, p), min(prev, p), p))
        prev = p
        t += timedelta(minutes=1)
    return ts, px


def ramp(a: float, b: float, pips_per_candle: float = 5.0) -> list[float]:
    d = pips_per_candle * PIP * (1 if b > a else -1)
    n = round(abs(b - a) / (pips_per_candle * PIP))
    return [round(a + d * (i + 1), 7) for i in range(n)]


# --- attribution --------------------------------------------------------------


def test_a_day_s_profit_lands_in_the_year_that_earned_it():
    """31 December's P&L belongs to December. Sampling equity on the first
    candle of a new day and filing the delta under the NEW day's month moves a
    year boundary by a day, every year, which is exactly the kind of error the
    per-year gate cannot see."""
    # A grid that takes profit on 30 and 31 December, replayed across midnight
    # into January.
    start = datetime(2023, 12, 30, 0, 0, tzinfo=UTC)
    prices = (ramp(1.10000, 1.09500) + ramp(1.09500, 1.10000)) * 3
    ts, px = series(start, prices)
    r = replay(GridConfig(step_pips=25, levels=4), ts, px)

    assert r["per_month"], "the fixture must produce some P&L"
    days = datetime.fromtimestamp(ts[-1], UTC).date()
    # Every dollar is attributed to a month inside the replayed window, and
    # nothing spills into a month the series never reached.
    assert set(r["per_month"]) <= {"2023-12", "2024-01"}
    if days.year == 2023:
        assert "2024-01" not in r["per_month"]


def test_the_per_year_totals_add_up_to_the_final_equity():
    start = datetime(2023, 6, 1, 0, 0, tzinfo=UTC)
    ts, px = series(start, (ramp(1.10000, 1.09400) + ramp(1.09400, 1.10000)) * 4)
    r = replay(GridConfig(step_pips=25, levels=4), ts, px)
    assert sum(r["per_year"].values()) == pytest.approx(
        r["final_equity"] - r["start_equity"], abs=0.02
    )
    assert sum(r["per_month"].values()) == pytest.approx(
        r["final_equity"] - r["start_equity"], abs=0.02
    )


def test_years_positive_counts_the_six_full_years_not_the_seven_calendar_ones():
    """2026 is January to June. Counting it would make the gate's denominator
    seven and quietly loosen "4 of 6"."""
    assert config.FULL_YEARS == (2020, 2021, 2022, 2023, 2024, 2025)
    assert config.PARTIAL_YEAR == 2026
    start = datetime(2026, 2, 2, 0, 0, tzinfo=UTC)
    ts, px = series(start, ramp(1.10000, 1.09400) + ramp(1.09400, 1.10000))
    r = replay(GridConfig(step_pips=25, levels=4), ts, px)
    assert r["years_total"] == 0, "no full year is in this window"
    assert r["years_positive"] == 0
    assert r["partial_year_pnl"] is not None, "2026 is still reported"


# --- drawdown and profit factor -----------------------------------------------


def test_drawdown_is_measured_from_the_opening_balance():
    """An unseeded curve takes its first sample as the peak, so a loss that
    happened before that sample is invisible."""
    assert _max_drawdown([1000.0, 900.0]) == pytest.approx(0.10)
    assert _max_drawdown([1000.0, 1200.0, 900.0]) == pytest.approx(0.25)
    assert _max_drawdown([1000.0, 1100.0, 1200.0]) == 0.0


def test_a_losing_first_day_shows_up_in_the_drawdown():
    start = datetime(2023, 6, 1, 0, 0, tzinfo=UTC)
    ts, px = series(start, ramp(1.10000, 1.11500))  # straight up: the grid bleeds
    r = replay(GridConfig(step_pips=25, levels=4), ts, px)
    assert r["equity_curve"][0] == 1000.0
    assert r["max_drawdown_pct"] > 0


def _trade(pnl: float) -> Trade:
    t = datetime(2023, 1, 1, tzinfo=UTC)
    return Trade(t, t, 1, 1.0, 1.1, 1.1, "buy_limit", "tp", pnl, 0.0, 0.0, pnl)


def test_profit_factor_is_gross_won_over_gross_lost():
    assert _profit_factor([_trade(3), _trade(-1), _trade(-1)]) == pytest.approx(1.5)
    assert _profit_factor([]) == 0.0
    assert _profit_factor([_trade(-5)]) == 0.0


def test_every_position_is_closed_by_the_end_so_the_curve_ends_at_cash():
    """A run that stops with positions open reports an equity that includes an
    unrealised mark, which is not a result."""
    start = datetime(2023, 6, 1, 0, 0, tzinfo=UTC)
    ts, px = series(start, ramp(1.10000, 1.09400))
    r = replay(GridConfig(step_pips=25, levels=4), ts, px)
    assert r["equity_curve"][-1] == r["final_equity"]
    assert any(t for t in [r]), "sanity"


# --- the gate -----------------------------------------------------------------


def test_the_gate_is_the_one_stated_before_the_sweep():
    from app.labs.forex_lab.report import GATE

    assert GATE == {
        "profit_factor_min": 1.3,
        "years_positive_min": 4,
        "years_positive_of": 6,
        "must_include_year": 2022,
        "max_drawdown_pct_max": 25.0,
        "best_month_share_max": 0.30,
    }


def test_the_gate_needs_all_five_conditions():
    from app.labs.forex_lab.report import gate_verdict

    passing = {
        "profit_factor": 1.4,
        "years_positive": 5,
        "max_drawdown_pct": 20.0,
        "best_month_share": 0.2,
        "total_return_pct": 30.0,
        "per_year": {"2022": 50.0},
    }
    assert gate_verdict(passing)["passed"] is True

    for key, bad in (
        ("profit_factor", 1.29),
        ("years_positive", 3),
        ("max_drawdown_pct", 25.0),
        ("best_month_share", 0.31),
    ):
        assert gate_verdict({**passing, key: bad})["passed"] is False
    assert gate_verdict({**passing, "per_year": {"2022": -1.0}})["passed"] is False
    assert gate_verdict({**passing, "profit_factor": None})["passed"] is False
    # Profit concentrated in one month cannot pass just because there was no
    # profit at all to concentrate.
    assert (
        gate_verdict({**passing, "total_return_pct": -5.0, "best_month_share": None})["passed"]
        is False
    )


# --- the report's honesty about its own coverage ------------------------------


def _sweep(first: str, last: str) -> dict:
    def result(name: str, mult: float) -> dict:
        return {
            "config": {
                "step_pips": 25,
                "levels": 4,
                "lots": 1.0,
                "stop_multiplier": mult,
                "name": name,
            },
            "start_equity": 1000.0,
            "final_equity": 1100.0,
            "total_return_pct": 10.0,
            "profit_factor": 1.4,
            "max_drawdown_pct": 5.0,
            "trades": 10,
            "min_equity": 950.0,
            "blown": False,
            "recenters": 1,
            "stopouts": 0,
            "rejected_fills": 0,
            "fills": 10,
            "spread_paid": 1.0,
            "swap_paid": -1.0,
            "recenter_loss": -1.0,
            "stopout_loss": 0.0,
            "tp_pnl": 100.0,
            "per_year": {str(y): 10.0 for y in range(2020, 2027)},
            "per_month": {"2020-01": 100.0},
            "years_positive": 6,
            "years_total": 6,
            "partial_year_pnl": 10.0,
            "best_month_share": 0.2,
        }

    return {
        "generated_at": "2026-09-13T00:00:00Z",
        "candles": 2_400_000,
        "first_minute": f"{first}T00:00:00Z",
        "last_minute": f"{last}T21:00:00Z",
        "results": [result("S25_N4_M1", 1.0), result("S25_N4_M0", 0.0)],
        "buy_and_hold": {
            "name": "buy_and_hold",
            "entry": 1.1,
            "exit": 1.2,
            "gross": 100.0,
            "swap": -10.0,
            "final_equity": 1090.0,
            "total_return_pct": 9.0,
        },
    }


def _render(tmp_path, first: str, last: str) -> str:
    import json

    from app.labs.forex_lab.report import write_report

    path = tmp_path / "sweep.json"
    path.write_text(json.dumps(_sweep(first, last)))
    dest = tmp_path / "REPORT.md"
    write_report(str(path), dest=dest)
    return dest.read_text()


def test_a_partial_window_is_declared_at_the_top_of_the_report(tmp_path):
    """A report headed 2020–2026 over eighteen months of data lies in its
    title. The banner is what stops a half-finished download being written up
    as a six-year backtest."""
    text = _render(tmp_path, "2020-01-01", "2021-04-12")
    assert "Partial coverage" in text
    assert text.splitlines()[0].endswith("2020-01-01 to 2021-04-12")
    assert "2026-06-30" in text, "it must still say what the brief asked for"


def test_a_full_window_gets_no_banner(tmp_path):
    text = _render(tmp_path, "2020-01-01", "2026-06-30")
    assert "Partial coverage" not in text
    assert text.splitlines()[0].endswith("2020-01-01 to 2026-06-30")


def test_the_baseline_comparison_is_stated_in_words(tmp_path):
    """The brief asks for a plain statement, not a table the reader has to
    subtract for themselves."""
    text = _render(tmp_path, "2020-01-01", "2026-06-30")
    assert "The hedged grid" in text
    assert "beat** the neutral-grid baseline" in text
    assert "beat** buy-and-hold." in text


def test_the_comparison_says_so_when_a_baseline_is_missing():
    """Quietly comparing against nothing is how a baseline goes missing without
    anyone noticing."""
    from app.labs.forex_lab.report import _verdict_sentence

    bh = {"final_equity": 1090.0}
    hedged = {"final_equity": 1100.0}
    assert "no neutral grid was run" in _verdict_sentence(hedged, None, bh)
    assert "nothing to compare" in _verdict_sentence(None, None, bh)
    assert "**beat** the neutral-grid baseline" in _verdict_sentence(
        hedged, {"final_equity": 1000.0}, bh
    )
    assert "**did not beat** the neutral-grid baseline" in _verdict_sentence(
        hedged, {"final_equity": 1200.0}, bh
    )
