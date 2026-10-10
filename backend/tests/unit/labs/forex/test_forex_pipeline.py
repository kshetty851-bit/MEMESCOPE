"""Signals plus engine composed in memory, and the three jobs built on them.

The properties defended here, each of which a backtest quietly loses when it is
wrong:

* a replay is deterministic - two runs over the same inputs are EQUAL;
* `trade_to` is a hard edge - nothing after it can reach a decision inside the
  window, so a development-window result cannot depend on later data;
* `trade_from` starts trading, not data - warm-up candles settle the
  indicators but never produce a trade;
* research chooses parameters on the development window ONLY - changing every
  candle after it must not move the search, the grid or the chosen parameters;
* stored results hold codes, never prose.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Any

import pytest

from app.labs.forex import jobs, meta, pipeline, prose
from app.labs.forex.codec import ConfigError
from app.labs.forex.data import resample
from app.labs.forex.pipeline import Market, NoDataError
from app.labs.forex.types import (
    BacktestConfig,
    Candle,
    StrategyId,
    Timeframe,
)
from tests.unit.labs.forex.synthetic import START, synthetic_m1

pytestmark = pytest.mark.unit

DAYS = 50
TRADE_START = START + timedelta(days=12)
TRADE_END = START + timedelta(days=DAYS)
CUT = START + timedelta(days=36)  # 15-minute aligned, inside the window

#: Two small grids keep the research tests quick; the default grids are
#: validated in `test_forex_codec`.
SMALL_GRID = {"params.rsi_period": [10, 14], "params.risk_reward": [1.5, 2.0]}


def _market(m1: list[Candle], cfg: BacktestConfig | None = None) -> Market:
    m5 = tuple(resample(m1, Timeframe.M1, Timeframe.M5).candles)
    m15 = tuple(resample(m1, Timeframe.M1, Timeframe.M15).candles)
    return Market(
        symbol="EURUSD",
        timeframe=Timeframe.M5,
        candles=m5,
        htf=m15,
        htf_timeframe=Timeframe.M15,
        lower=tuple(m1),
        sources=("synthetic",),
        exec_derived="resampled_from_1m",
        htf_derived="resampled",
    )


def _scaled_after(m1: list[Candle], cut: Any, factor: float) -> list[Candle]:
    """The same candles, with every price at or after `cut` multiplied."""
    return [
        c
        if c.open_time < cut
        else replace(
            c,
            open=round(c.open * factor, 5),
            high=round(c.high * factor, 5),
            low=round(c.low * factor, 5),
            close=round(c.close * factor, 5),
        )
        for c in m1
    ]


@pytest.fixture(scope="module")
def m1() -> list[Candle]:
    return synthetic_m1(DAYS)


@pytest.fixture(scope="module")
def market(m1: list[Candle]) -> Market:
    return _market(m1)


def _cfg(strategy: StrategyId) -> BacktestConfig:
    return meta.default_config(strategy)


# --- the replay --------------------------------------------------------------


@pytest.mark.parametrize("strategy", list(StrategyId))
def test_two_runs_over_the_same_inputs_are_equal(market: Market, strategy: StrategyId) -> None:
    cfg = _cfg(strategy)
    first = pipeline.run(cfg, market, TRADE_START, TRADE_END)
    second = pipeline.run(cfg, market, TRADE_START, TRADE_END)
    assert first == second
    assert first.trades, "the synthetic series should trade; otherwise this proves nothing"


@pytest.mark.parametrize("strategy", list(StrategyId))
def test_data_after_trade_to_cannot_change_a_window(
    m1: list[Candle], market: Market, strategy: StrategyId
) -> None:
    """A run over [start, CUT) equals the same run on a market that ENDS at CUT,
    and on one whose later candles are wildly different."""
    cfg = _cfg(strategy)
    base = pipeline.run(cfg, market, TRADE_START, CUT)

    truncated = _market([c for c in m1 if c.open_time < CUT])
    assert pipeline.run(cfg, truncated, TRADE_START, CUT) == base

    shifted = _market(_scaled_after(m1, CUT, 1.15))
    assert pipeline.run(cfg, shifted, TRADE_START, CUT) == base
    assert base.trades


def test_nothing_trades_before_trade_from_but_warm_up_settles_the_indicators(
    m1: list[Candle], market: Market
) -> None:
    cfg = _cfg(StrategyId.RSI_PULLBACK)
    warmed = pipeline.run(cfg, market, TRADE_START, TRADE_END)
    assert all(t.signal_time >= TRADE_START for t in warmed.trades)

    cold = _market([c for c in m1 if c.open_time >= TRADE_START])
    cold_run = pipeline.run(cfg, cold, TRADE_START, TRADE_END)
    # Without warm-up the 200-bar trend average is not settled for days, so the
    # first trade comes later - which is exactly what warm-up exists to prevent.
    assert warmed.trades[0].signal_time < cold_run.trades[0].signal_time


def test_the_edges_are_checked(market: Market) -> None:
    cfg = _cfg(StrategyId.RSI_PULLBACK)
    with pytest.raises(ValueError, match="end_not_after_start"):
        pipeline.run(cfg, market, TRADE_END, TRADE_START)
    with pytest.raises(NoDataError):
        pipeline.run(
            cfg, market, TRADE_END + timedelta(days=30), TRADE_END + timedelta(days=60)
        )
    with pytest.raises(NoDataError):
        pipeline.run(cfg, market, START - timedelta(days=30), START - timedelta(days=20))
    with pytest.raises(ValueError, match="market_does_not_match_config"):
        pipeline.run(replace(cfg, timeframe=Timeframe.M15), market, TRADE_START, TRADE_END)


def test_a_missing_trend_timeframe_is_refused_not_guessed(market: Market) -> None:
    cfg = _cfg(StrategyId.RSI_PULLBACK)
    no_htf = replace(market, htf=None, htf_timeframe=None)
    with pytest.raises(ValueError, match="market_lacks_trend_timeframe"):
        pipeline.run(cfg, no_htf, TRADE_START, TRADE_END)
    # With the filter off it is not needed.
    off = replace(cfg, params=replace(cfg.params, trend_filter=False))
    assert pipeline.run(off, no_htf, TRADE_START, TRADE_END).bars > 0


def test_warm_up_covers_the_slowest_indicator() -> None:
    cfg = _cfg(StrategyId.RSI_PULLBACK)
    assert pipeline.warmup_for(cfg) == timedelta(days=10)
    slow = replace(
        cfg,
        params=replace(cfg.params, trend_timeframe=Timeframe.H1, trend_ema_period=500),
    )
    # 500 hourly bars x 1.5 for weekends.
    assert pipeline.warmup_for(slow) == timedelta(hours=750)


def test_fingerprint_names_the_data(market: Market, m1: list[Candle]) -> None:
    cfg = _cfg(StrategyId.RSI_PULLBACK)
    fp = pipeline.fingerprint(market.candles, cfg.symbol, cfg.timeframe)
    assert len(fp) == 64
    assert fp == pipeline.fingerprint(market.candles, cfg.symbol, cfg.timeframe)
    assert fp != pipeline.fingerprint(market.candles[:-1], cfg.symbol, cfg.timeframe)
    nudged = list(market.candles)
    nudged[10] = replace(nudged[10], close=nudged[10].close + 0.0001)
    assert fp != pipeline.fingerprint(nudged, cfg.symbol, cfg.timeframe)
    assert pipeline.combined_fingerprint([fp]) == fp
    assert pipeline.combined_fingerprint([fp, "x"]) != fp


# --- options -------------------------------------------------------------------


def test_options_defaults_and_bounds() -> None:
    o = jobs.parse_options(None)
    assert (o.dev_pct, o.val_pct, o.mc_iterations) == (60.0, 20.0, 1000)
    assert (o.train_days, o.test_days) == (90, 30)
    assert o.stress_multipliers == (1.0, 1.5, 2.0, 3.0)
    parsed = jobs.parse_options({"walk_forward": {"train_days": 30, "test_days": 10}})
    assert (parsed.train_days, parsed.test_days) == (30, 10)
    for bad in (
        {"dev_pct": 95},
        {"dev_pct": 70, "val_pct": 30},
        {"mc_iterations": 5},
        {"mc_iterations": 10**6},
        {"stress_multipliers": []},
        {"stress_multipliers": [0.1]},
        {"walk_forward": {"train_days": 1}},
        {"surprise": 1},
        {"grid": {}},
        "nope",
    ):
        with pytest.raises(ConfigError):
            jobs.parse_options(bad)  # type: ignore[arg-type]


def test_stress_doubles_every_cost() -> None:
    cfg = _cfg(StrategyId.RSI_PULLBACK)
    stressed = jobs.stress_config(cfg, 2.0)
    assert stressed.costs.spread_pips == cfg.costs.spread_pips * 2
    assert stressed.costs.slippage_pips == cfg.costs.slippage_pips * 2
    assert stressed.costs.commission_per_lot_side == cfg.costs.commission_per_lot_side * 2
    assert stressed.risk == cfg.risk


# --- backtest job ----------------------------------------------------------------


@pytest.fixture(scope="module")
def backtest(market: Market) -> tuple[dict[str, Any], dict[str, Any]]:
    return jobs.run_backtest_job(
        _cfg(StrategyId.RSI_PULLBACK), market, TRADE_START, TRADE_END, jobs.Options()
    )


def test_the_backtest_result_is_json_and_carries_codes_not_prose(
    backtest: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    result, summary = backtest
    text = json.dumps(result)  # no Decimal, datetime or NaN may survive
    assert "NaN" not in text and "Infinity" not in text
    assert '"text"' not in text, "prose must be rendered at read time, never stored"
    assert result["type"] == "backtest"
    assert (
        summary["total_trades"] == result["metrics"]["total_trades"] == len(result["trades"])
    )
    assert result["assumptions"][0] == {"code": "entry_next_bar_open"}
    assert len(result["assumptions"]) == 8


def test_money_is_a_string_and_prices_are_numbers(
    backtest: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    result, _ = backtest
    m = result["metrics"]
    for key in (
        "starting_balance",
        "ending_balance",
        "net_profit",
        "gross_profit",
        "total_commission",
    ):
        assert isinstance(m[key], str), key
    assert m["starting_balance"] == "1000"
    t = result["trades"][0]
    for key in ("risk_usd", "gross_pnl", "commission", "net_pnl", "financing"):
        assert isinstance(t[key], str), key
    for key in ("entry_price", "exit_price", "stop_price"):
        assert isinstance(t[key], float), key
    point = result["equity_curve"][0]
    assert isinstance(point["balance"], str) and isinstance(point["equity"], str)


def test_every_trade_is_kept_losers_included(
    backtest: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    result, _ = backtest
    trades = result["trades"]
    assert [t["id"] for t in trades] == sorted(t["id"] for t in trades)
    assert any(float(t["net_pnl"]) < 0 for t in trades)
    m = result["metrics"]
    assert m["wins"] + m["losses"] + m["breakeven"] == len(trades)
    assert all(t["duration_minutes"] >= 0 for t in trades)


def test_skipped_counts_match_and_text_is_rendered_on_read(
    backtest: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    result, _ = backtest
    assert sum(result["skipped"].values()) == sum(r["count"] for r in result["skipped_text"])
    rendered = prose.render(result)
    for row in rendered["skipped_text"]:
        assert row["text"] and row["text"] != row["code"]
    for note in rendered["data"].get("notes", []):
        assert note["text"]
    assert rendered["monte_carlo"]["assumptions"][0]["text"]
    assert rendered["targets"]["disclaimers"][0]["text"]


def test_the_data_block_reports_where_candles_came_from(
    backtest: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    data = backtest[0]["data"]
    assert data["symbol"] == "EURUSD" and data["timeframe"] == "5m"
    assert data["sources"] == ["synthetic"]
    assert data["lower_tf_available"] is True
    assert data["htf_derived"] == "resampled"
    assert data["quality_grade"] in {"good", "fair", "poor"}
    assert 0 < data["coverage_pct"] <= 100


def test_the_target_analysis_describes_history_only(
    backtest: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    targets = backtest[0]["targets"]
    assert [r["target_pct"] for r in targets["rows"]] == [5, 10, 20, 50, 100]
    assert {d["code"] for d in targets["disclaimers"]} >= {
        "historical_observation_not_forecast",
        "no_position_size_increase_to_force_target",
    }
    assert targets["risk_of_ruin"]["assumptions"]


def test_backtest_progress_is_monotonic(market: Market) -> None:
    seen: list[int] = []
    jobs.run_backtest_job(
        _cfg(StrategyId.RSI_PULLBACK),
        market,
        TRADE_START,
        TRADE_END,
        jobs.Options(mc_iterations=100),
        lambda pct, _msg: seen.append(pct),
    )
    assert seen == sorted(seen) and seen[-1] <= 99


# --- research job ----------------------------------------------------------------


def _research(m: Market, **kw: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    opts = jobs.Options(grid=SMALL_GRID, mc_iterations=100, train_days=90, test_days=30, **kw)
    return jobs.run_research_job(
        _cfg(StrategyId.RSI_PULLBACK), m, TRADE_START, TRADE_END, opts
    )


@pytest.fixture(scope="module")
def research(market: Market) -> tuple[dict[str, Any], dict[str, Any]]:
    return _research(market)


def test_research_is_deterministic(
    market: Market, research: tuple[dict[str, Any], dict[str, Any]]
) -> None:
    assert _research(market) == research


def test_the_split_is_contiguous_and_in_time_order(
    research: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    split = research[0]["split"]
    assert split["development"]["end"] == split["validation"]["start"]
    assert split["validation"]["end"] == split["test"]["start"]
    assert split["development"]["start"] < split["development"]["end"] < split["test"]["end"]
    for name in ("development", "validation", "test"):
        assert research[0][name]["window"] == split[name]


def test_parameters_are_chosen_on_the_development_window_only(
    m1: list[Candle], research: tuple[dict[str, Any], dict[str, Any]]
) -> None:
    """Rewrite every candle after the development window. The search, its grid
    and the winner must be unchanged: nothing from validation or test reached
    the choice. The test period itself, of course, now reads differently."""
    result, _ = research
    dev_end = datetime.fromisoformat(result["split"]["development"]["end"])
    altered = _research(_market(_scaled_after(m1, dev_end, 1.2)))[0]

    assert altered["optimisation"] == result["optimisation"]
    assert altered["chosen_params"] == result["chosen_params"]
    assert altered["selection_note"] == {"code": "selection_on_development_only"}
    assert altered["development"] == result["development"]
    assert altered["test"] != result["test"], (
        "the test window should have reacted to the change"
    )
    assert altered["stability"] == result["stability"]


def test_research_reports_every_section_the_contract_names(
    research: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    result, summary = research
    json.dumps(result)
    assert set(result) >= {
        "type", "split", "optimisation", "chosen_params", "selection_note", "development",
        "validation", "test", "walk_forward", "sensitivity", "stability", "cost_stress",
        "monte_carlo", "bootstrap", "regimes", "baseline", "targets", "scorecard",
    }  # fmt: skip
    assert len(result["optimisation"]["rows"]) == 4
    assert result["optimisation"]["best"] is not None
    assert set(result["sensitivity"]) == set(SMALL_GRID)
    assert [r["multiplier"] for r in result["cost_stress"]] == [1.0, 1.5, 2.0, 3.0]
    assert set(result["targets"]) == {"full", "out_of_sample"}
    assert summary["verdict_code"] == result["scorecard"]["verdict"]["code"]
    assert result["scorecard"]["rank"] == 1
    assert len(result["trades"]) == summary["total_trades"]
    for window in ("development", "validation", "test"):
        assert set(result[window]) == {
            "window",
            "metrics",
            "months",
            "equity_curve",
            "trade_count",
        }


def test_a_window_too_short_for_walk_forward_says_so_and_the_rest_stands(
    research: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    wf = research[0]["walk_forward"]
    assert wf["folds"] == []
    assert wf["efficiency"] is None
    assert wf["efficiency_note"] == {"code": "no_fold_fits_range"}


def test_walk_forward_runs_when_the_window_fits(market: Market) -> None:
    opts = jobs.Options(
        grid={"params.rsi_period": [10, 14]}, mc_iterations=100, train_days=14, test_days=7
    )
    result, _ = jobs.run_research_job(
        _cfg(StrategyId.RSI_PULLBACK), market, TRADE_START, TRADE_END, opts
    )
    folds = result["walk_forward"]["folds"]
    assert len(folds) >= 2
    for prev, nxt in pairwise(folds):
        assert prev["test"]["end"] <= nxt["test"]["end"]
        assert prev["train"]["end"] == prev["test"]["start"], (
            "a fold trains strictly before it tests"
        )


def test_a_grid_nothing_can_rank_falls_back_to_the_submitted_config(market: Market) -> None:
    """Every cell below the trade minimum: say so, and use the config as given."""
    cfg = _cfg(StrategyId.LONDON_BREAKOUT)
    result, _ = jobs.run_research_job(
        cfg,
        market,
        TRADE_START,
        START + timedelta(days=24),
        jobs.Options(grid={"params.risk_reward": [1.5, 2.0]}, mc_iterations=100),
    )
    assert result["optimisation"]["best"] is None, (
        "the window is meant to be too quiet to rank"
    )
    assert result["selection_note"] == {"code": "no_eligible_parameters_base_config_used"}
    assert result["chosen_params"] == {}


def test_research_refuses_a_grid_outside_the_bounds(market: Market) -> None:
    with pytest.raises(ConfigError):
        jobs.run_research_job(
            _cfg(StrategyId.RSI_PULLBACK),
            market,
            TRADE_START,
            TRADE_END,
            jobs.Options(grid={"params.rsi_period": [1, 14]}),
        )


# --- compare job -----------------------------------------------------------------


@pytest.fixture(scope="module")
def compare(market: Market) -> tuple[dict[str, Any], dict[str, Any]]:
    cfgs = [_cfg(s) for s in StrategyId]
    return jobs.run_compare_job(
        cfgs, [market] * 3, TRADE_START, TRADE_END, jobs.Options(mc_iterations=100)
    )


def test_compare_ranks_every_strategy_once(
    compare: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    result, summary = compare
    json.dumps(result)
    cards = result["scorecards"]
    assert [c["rank"] for c in cards] == [1, 2, 3]
    assert {c["strategy"] for c in cards} == {s.value for s in StrategyId}
    assert set(result["per_strategy"]) == {s.value for s in StrategyId}
    scored = [c["robustness_score"] for c in cards if c["robustness_score"] is not None]
    assert scored == sorted(scored, reverse=True)
    # Unscored cards (too few trades) rank last, never first.
    flags = [c["robustness_score"] is None for c in cards]
    assert flags == sorted(flags)
    assert summary["verdict_code"] == cards[0]["verdict"]["code"]


def test_compare_never_optimises_the_params_it_was_given(
    compare: tuple[dict[str, Any], dict[str, Any]], market: Market
) -> None:
    """The `full` figures are the given config's own backtest, not a tuned one."""
    result, _ = compare
    solo, _ = jobs.run_backtest_job(
        _cfg(StrategyId.RSI_PULLBACK),
        market,
        TRADE_START,
        TRADE_END,
        jobs.Options(mc_iterations=100),
    )
    full = result["per_strategy"]["rsi_pullback"]["full"]
    assert full["trades"] == solo["metrics"]["total_trades"]
    assert full["net_return_pct"] == solo["metrics"]["net_return_pct"]


def test_two_configs_of_one_strategy_get_distinct_names(market: Market) -> None:
    base = _cfg(StrategyId.RSI_PULLBACK)
    other = replace(base, params=replace(base.params, rsi_period=21))
    result, _ = jobs.run_compare_job(
        [base, other],
        [market, market],
        TRADE_START,
        TRADE_END,
        jobs.Options(mc_iterations=100),
    )
    names = [c["name"] for c in result["scorecards"]]
    assert len(set(names)) == 2
    assert len(result["per_strategy"]) == 2


def test_compare_needs_a_market_for_each_config(market: Market) -> None:
    with pytest.raises(ValueError, match="compare_needs_a_market_per_config"):
        jobs.run_compare_job(
            [_cfg(StrategyId.RSI_PULLBACK)], [], TRADE_START, TRADE_END, jobs.Options()
        )


# --- cancellation ------------------------------------------------------------------


def test_a_cancelled_job_stops_at_its_next_progress_report(market: Market) -> None:
    """The worker thread cannot be killed, so cancellation rides on the progress
    callback: a research run reports after every replay, and raising there ends
    the thread within one replay instead of holding a shutdown open for minutes."""
    from app.labs.forex.service import RunCancelledError, _Holder

    holder = _Holder()
    calls = 0

    def progress(pct: int, message: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            holder.cancelled = True
        holder(pct, message)

    with pytest.raises(RunCancelledError):
        jobs.run_research_job(
            _cfg(StrategyId.RSI_PULLBACK),
            market,
            TRADE_START,
            TRADE_END,
            jobs.Options(grid=SMALL_GRID, mc_iterations=100),
            progress=progress,
        )
    assert calls == 3, "stopped on the first report after cancellation"
