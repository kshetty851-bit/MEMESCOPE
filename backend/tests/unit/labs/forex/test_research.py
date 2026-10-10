"""Research helpers are tested with fake runners, so each property is about the
helper (what it selects, what it never looks at), not about any strategy."""

from __future__ import annotations

import statistics
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise

import pytest

from app.labs.forex.metrics import Metrics, compute_metrics
from app.labs.forex.research import (
    GridRow,
    Window,
    baseline_comparison,
    bootstrap_ci,
    chronological_split,
    cost_stress,
    grid,
    monte_carlo,
    objective,
    optimise,
    parameter_stability,
    regime_breakdown,
    sensitivity,
    walk_forward,
    with_param,
)
from app.labs.forex.types import (
    BacktestConfig,
    BacktestResult,
    Candle,
    Direction,
    EquityPoint,
    ExitReason,
    StopMethod,
    StrategyId,
    Trade,
)

pytestmark = pytest.mark.unit

T0 = datetime(2024, 1, 1, tzinfo=UTC)
D = Decimal
BASE = BacktestConfig(strategy=StrategyId.RSI_PULLBACK)


def mk_trade(i: int, r: float, entry: datetime) -> Trade:
    net = D(str(round(r * 10, 2)))
    return Trade(
        id=i,
        direction=Direction.LONG,
        signal_time=entry,
        entry_time=entry,
        exit_time=entry + timedelta(hours=1),
        entry_price=1.1,
        exit_price=1.1,
        stop_price=1.09,
        take_profit_price=None,
        units=1000,
        risk_usd=D("10"),
        gross_pnl=net,
        commission=D(0),
        spread_slippage_cost=D(0),
        financing=D(0),
        net_pnl=net,
        r_multiple=r,
        exit_reason=ExitReason.STOP_LOSS,
        reason="t",
    )


def mk_result(
    cfg: BacktestConfig, start: datetime, end: datetime, rs: list[float]
) -> BacktestResult:
    """`rs` trades spread evenly across [start, end), equity chained from them."""
    step = (end - start) / (len(rs) + 1)
    trades = tuple(mk_trade(i, r, start + step * (i + 1)) for i, r in enumerate(rs))
    bal = cfg.risk.initial_capital
    curve = []
    for t in trades:
        bal += t.net_pnl
        curve.append(EquityPoint(t.exit_time, bal, bal))
    return BacktestResult(
        config=cfg,
        start=start,
        end=end,
        bars=10,
        trades=trades,
        equity_curve=tuple(curve),
        skipped=(),
        final_balance=bal,
    )


def metrics_of(rs: list[float]) -> Metrics:
    return compute_metrics(mk_result(BASE, T0, T0 + timedelta(days=30), rs))


# ---------------------------------------------------------------- with_param


def test_with_param_sets_nested_fields_and_leaves_original_untouched() -> None:
    """Frozen configs are copied, never mutated: a grid cell cannot leak into another."""
    cfg = with_param(BASE, "params.rsi_period", 21)
    assert cfg.params.rsi_period == 21
    assert BASE.params.rsi_period == 14
    assert cfg.costs == BASE.costs


def test_with_param_coerces_to_existing_field_type() -> None:
    assert with_param(BASE, "params.rsi_period", 21.0).params.rsi_period == 21
    assert with_param(BASE, "costs.spread_pips", 2).costs.spread_pips == 2.0
    assert isinstance(with_param(BASE, "costs.spread_pips", 2).costs.spread_pips, float)
    risk = with_param(BASE, "risk.risk_per_trade_pct", 1.5).risk.risk_per_trade_pct
    assert risk == D("1.5") and isinstance(risk, Decimal)
    assert with_param(BASE, "params.stop_method", "fixed_pips").params.stop_method == (
        StopMethod.FIXED_PIPS
    )
    assert with_param(BASE, "params.trend_filter", False).params.trend_filter is False


def test_with_param_rejects_unknown_paths_and_lossy_values() -> None:
    """A typo in a path must fail loudly, not silently run the unchanged config."""
    with pytest.raises(ValueError):
        with_param(BASE, "params.no_such_field", 1)
    with pytest.raises(ValueError):
        with_param(BASE, "nope.rsi_period", 1)
    with pytest.raises(ValueError):
        with_param(BASE, "params.rsi_period.deeper", 1)
    with pytest.raises(ValueError):
        with_param(BASE, "params.rsi_period", 21.5)
    with pytest.raises(ValueError):
        with_param(BASE, "params.trend_filter", 1)


# ------------------------------------------------------------------- windows


def test_split_is_contiguous_ordered_and_day_aligned() -> None:
    """No instant belongs to two windows, and cuts fall on UTC midnights."""
    start, end = datetime(2023, 1, 1, 5, tzinfo=UTC), datetime(2024, 1, 1, 7, tzinfo=UTC)
    s = chronological_split(start, end)
    assert s.development.start == start and s.test.end == end
    assert s.development.end == s.validation.start
    assert s.validation.end == s.test.start
    assert start < s.development.end < s.validation.end < end
    for cut in (s.development.end, s.validation.end):
        assert (cut.hour, cut.minute, cut.second) == (0, 0, 0)
    dev_days = (s.development.end - start).days
    assert 210 <= dev_days <= 220  # ~60% of the span


@pytest.mark.parametrize(
    ("dev", "val"), [(0.0, 20.0), (60.0, 0.0), (80.0, 20.0), (90.0, 30.0), (-1.0, 20.0)]
)
def test_split_rejects_invalid_fractions(dev: float, val: float) -> None:
    with pytest.raises(ValueError):
        chronological_split(T0, T0 + timedelta(days=100), dev, val)


def test_split_rejects_reversed_or_tiny_ranges() -> None:
    with pytest.raises(ValueError):
        chronological_split(T0, T0)
    with pytest.raises(ValueError):
        chronological_split(T0 + timedelta(hours=1), T0 + timedelta(hours=5))


# ---------------------------------------------------------------------- grid


def test_grid_is_the_cartesian_product_with_configs_applied() -> None:
    space: dict[str, list[object]] = {
        "params.rsi_period": [10, 14, 21],
        "costs.spread_pips": [1, 2],
    }
    cells = grid(BASE, space)
    assert len(cells) == 6
    assert {(p["params.rsi_period"], p["costs.spread_pips"]) for p, _ in cells} == {
        (a, b) for a in (10, 14, 21) for b in (1, 2)
    }
    for params, cfg in cells:
        assert cfg.params.rsi_period == params["params.rsi_period"]
        assert cfg.costs.spread_pips == float(params["costs.spread_pips"])  # type: ignore[arg-type]


def test_grid_with_empty_space_is_the_base_config() -> None:
    assert grid(BASE, {}) == [({}, BASE)]


# ----------------------------------------------------------------- objective


def test_objective_withheld_below_minimum_trades() -> None:
    """A strong-looking 19-trade cell is not rankable."""
    assert objective(metrics_of([1.0] * 19)) is None
    assert objective(metrics_of([1.0] * 20)) is not None


def test_objective_rewards_expectancy_with_capped_evidence() -> None:
    """Evidence stops counting past 100 trades, so volume alone cannot win."""
    s100 = objective(metrics_of([1.0, -0.5] * 50))
    s200 = objective(metrics_of([1.0, -0.5] * 100))
    assert s100 is not None and s200 is not None
    assert s100 > 0
    assert s200 == pytest.approx(s100, rel=0.05)


def test_objective_drawdown_never_improves_a_losing_score() -> None:
    """Scaling a negative score by (1 - dd) would reward deeper drawdowns."""
    shallow = objective(metrics_of([-0.2] * 20))
    deep = objective(metrics_of([-0.2] * 10 + [-3.0] + [-0.2] * 9))
    assert shallow is not None and deep is not None
    assert shallow < 0 and deep < shallow


# ------------------------------------------------------------------ optimise


def rsi_runner(good: int = 14, calls: list[tuple[int, datetime, datetime]] | None = None):  # type: ignore[no-untyped-def]
    def run(cfg: BacktestConfig, start: datetime, end: datetime) -> BacktestResult:
        if calls is not None:
            calls.append((cfg.params.rsi_period, start, end))
        rs = [0.5, 0.1] * 15 if cfg.params.rsi_period == good else [-0.3, 0.1] * 15
        return mk_result(cfg, start, end, rs)

    return run


def test_optimise_picks_best_score_and_reports_every_cell() -> None:
    """All cells are returned, including the losing ones; only `best` is chosen."""
    space: dict[str, list[object]] = {"params.rsi_period": [10, 14, 21]}
    res = optimise(BASE, space, rsi_runner(), Window(T0, T0 + timedelta(days=60)))
    assert [r.params["params.rsi_period"] for r in res.rows] == [10, 14, 21]
    assert res.best is not None and res.best.params["params.rsi_period"] == 14
    assert res.rows[0].expectancy_r is not None and res.rows[0].expectancy_r < 0


def test_optimise_never_selects_a_cell_with_too_few_trades() -> None:
    """A spectacular 5-trade cell is noise; no eligible cell means no best."""

    def run(cfg: BacktestConfig, start: datetime, end: datetime) -> BacktestResult:
        return mk_result(cfg, start, end, [5.0] * 5)

    res = optimise(
        BASE, {"params.rsi_period": [10, 14]}, run, Window(T0, T0 + timedelta(days=9))
    )
    assert res.best is None
    assert all(r.score is None for r in res.rows)


def test_optimise_tie_goes_to_first_cell() -> None:
    """Equal scores resolve by grid order so reruns are identical."""

    def run(cfg: BacktestConfig, start: datetime, end: datetime) -> BacktestResult:
        return mk_result(cfg, start, end, [0.5, -0.1] * 15)

    res = optimise(
        BASE, {"params.rsi_period": [7, 9, 11]}, run, Window(T0, T0 + timedelta(days=9))
    )
    assert res.best is not None and res.best.params["params.rsi_period"] == 7


# -------------------------------------------------------------- walk-forward


def regime_switch_runner(cutoff: datetime, calls: list[tuple[int, datetime, datetime]]):  # type: ignore[no-untyped-def]
    """Period A (before cutoff): rsi 10 works. Period B (after): rsi 21 works."""

    def run(cfg: BacktestConfig, start: datetime, end: datetime) -> BacktestResult:
        calls.append((cfg.params.rsi_period, start, end))
        good = 10 if start < cutoff else 21
        rs = [0.6, 0.0] * 15 if cfg.params.rsi_period == good else [-0.4, 0.1] * 15
        return mk_result(cfg, start, end, rs)

    return run


def test_walk_forward_chooses_on_train_only_and_trades_the_next_window() -> None:
    """The test window is out of sample: when the market flips just after the
    train window, the train-chosen parameter must still be applied and its
    poor test result reported, not swapped for the test-window winner."""
    calls: list[tuple[int, datetime, datetime]] = []
    cutoff = T0 + timedelta(days=100)
    space: dict[str, list[object]] = {"params.rsi_period": [10, 21]}
    wf = walk_forward(
        BASE, space, regime_switch_runner(cutoff, calls), T0, T0 + timedelta(days=130), 90, 10
    )
    assert len(wf.folds) == 4
    first = wf.folds[0]
    assert first.chosen_params == {"params.rsi_period": 10}
    assert first.test_metrics is not None and first.test_metrics.expectancy_r is not None
    assert first.test_metrics.expectancy_r > 0  # test starts day 90, before cutoff
    last = wf.folds[-1]
    assert last.chosen_params == {
        "params.rsi_period": 10
    }  # train ends day 120 > cutoff? see below
    assert wf.oos_summary["trades"] == len(wf.oos_trades) == 30 * 4


def test_walk_forward_train_calls_never_touch_the_test_window() -> None:
    """Every run issued while choosing parameters ends at or before train end."""
    calls: list[tuple[int, datetime, datetime]] = []
    space: dict[str, list[object]] = {"params.rsi_period": [10, 21]}
    wf = walk_forward(
        BASE,
        space,
        regime_switch_runner(T0 + timedelta(days=1000), calls),
        T0,
        T0 + timedelta(days=60),
        30,
        10,
        step_days=10,
    )
    assert len(wf.folds) == 3
    for fold in wf.folds:
        assert fold.train.end == fold.test.start
        assert fold.train.start < fold.train.end <= fold.test.start < fold.test.end
        in_train = [c for c in calls if c[1] == fold.train.start and c[2] == fold.train.end]
        assert len(in_train) == 2  # one run per grid cell, train window only
        assert not any(
            c[1] < fold.test.end
            and c[2] > fold.train.end
            and c[1] < fold.train.end
            and c[2] != fold.train.end
            for c in calls
            if c[1] == fold.train.start
        )


def test_walk_forward_oos_windows_do_not_overlap() -> None:
    calls: list[tuple[int, datetime, datetime]] = []
    space: dict[str, list[object]] = {"params.rsi_period": [10, 21]}
    wf = walk_forward(
        BASE, space, regime_switch_runner(T0, calls), T0, T0 + timedelta(days=100), 40, 20
    )
    tests = [f.test for f in wf.folds]
    assert all(a.end <= b.start for a, b in pairwise(tests))


def test_walk_forward_efficiency_is_test_over_train_expectancy() -> None:
    calls: list[tuple[int, datetime, datetime]] = []
    wf = walk_forward(
        BASE,
        {"params.rsi_period": [10, 21]},
        regime_switch_runner(T0 + timedelta(days=1000), calls),
        T0,
        T0 + timedelta(days=60),
        30,
        10,
    )
    assert wf.efficiency == pytest.approx(1.0)


def test_walk_forward_records_fold_without_eligible_parameters() -> None:
    """If no train cell has enough trades the fold is kept, flagged, and untraded."""

    def run(cfg: BacktestConfig, start: datetime, end: datetime) -> BacktestResult:
        return mk_result(cfg, start, end, [1.0] * 3)

    wf = walk_forward(
        BASE, {"params.rsi_period": [10]}, run, T0, T0 + timedelta(days=40), 30, 10
    )
    assert len(wf.folds) == 1
    assert wf.folds[0].note == "no_eligible_parameters"
    assert wf.folds[0].chosen_params is None and wf.folds[0].test_metrics is None
    assert wf.oos_trades == () and wf.efficiency is None


def test_walk_forward_rejects_bad_geometry() -> None:
    def run(cfg: BacktestConfig, start: datetime, end: datetime) -> BacktestResult:
        return mk_result(cfg, start, end, [1.0] * 25)

    space: dict[str, list[object]] = {"params.rsi_period": [10]}
    with pytest.raises(ValueError):
        walk_forward(BASE, space, run, T0, T0 + timedelta(days=100), 0, 10)
    with pytest.raises(ValueError):  # overlapping test windows would double-count trades
        walk_forward(BASE, space, run, T0, T0 + timedelta(days=100), 30, 10, step_days=5)
    with pytest.raises(ValueError):
        walk_forward(BASE, space, run, T0, T0 + timedelta(days=20), 30, 10)


# --------------------------------------------------------------- sensitivity


def test_sensitivity_runs_each_value_in_order() -> None:
    rows = sensitivity(
        BASE,
        "params.rsi_period",
        [10, 14, 21],
        rsi_runner(),
        Window(T0, T0 + timedelta(days=30)),
    )
    assert [r.value for r in rows] == [10, 14, 21]
    assert [r.trades for r in rows] == [30, 30, 30]
    assert rows[1].expectancy_r is not None and rows[1].expectancy_r > 0
    assert rows[0].expectancy_r is not None and rows[0].expectancy_r < 0


# ----------------------------------------------------------------- stability

SPACE: dict[str, list[object]] = {"a": [1, 2, 3], "b": [10, 20, 30]}


def cell(a: int, b: int, e: float | None, trades: int = 50) -> GridRow:
    score = None if e is None else e * 10
    return GridRow({"a": a, "b": b}, trades, 0.0, e, None, 5.0, score)


def full_grid(values: dict[tuple[int, int], float]) -> list[GridRow]:
    return [cell(a, b, values[(a, b)]) for a in (1, 2, 3) for b in (10, 20, 30)]


def test_isolated_peak_is_flagged_when_neighbours_are_not_positive() -> None:
    """A lone spike among losing cells is the signature of a fit to noise."""
    vals = {(a, b): -0.1 for a in (1, 2, 3) for b in (10, 20, 30)}
    vals[(2, 20)] = 0.5
    rep = parameter_stability(full_grid(vals), SPACE)
    assert rep.best_params == {"a": 2, "b": 20}
    assert rep.neighbour_count == 4  # diagonals differ in two parameters
    assert rep.neighbours_positive_pct == 0.0
    assert rep.isolated_peak is True
    assert rep.best_vs_neighbour_median_ratio is None  # median not positive
    assert rep.positive_cells_pct == pytest.approx(1 / 9 * 100)


def test_plateau_is_not_isolated() -> None:
    vals = {(a, b): 0.2 for a in (1, 2, 3) for b in (10, 20, 30)}
    vals[(2, 20)] = 0.4
    rep = parameter_stability(full_grid(vals), SPACE)
    assert rep.isolated_peak is False
    assert rep.neighbours_positive_pct == 100.0
    assert rep.best_vs_neighbour_median_ratio == pytest.approx(2.0)
    assert rep.positive_cells_pct == 100.0


def test_corner_cell_has_fewer_neighbours() -> None:
    vals = {(a, b): 0.1 for a in (1, 2, 3) for b in (10, 20, 30)}
    vals[(1, 10)] = 0.9
    rep = parameter_stability(full_grid(vals), SPACE)
    assert rep.best_params == {"a": 1, "b": 10}
    assert rep.neighbour_count == 2


def test_stability_without_any_eligible_cell() -> None:
    rows = [cell(1, 10, None), cell(2, 10, None)]
    rep = parameter_stability(rows, SPACE)
    assert rep.best_params is None and rep.isolated_peak is False
    assert rep.positive_cells_pct == 0.0


def test_negative_best_is_not_called_an_isolated_peak() -> None:
    """The flag means 'a positive result that does not generalise'."""
    vals = {(a, b): -0.5 for a in (1, 2, 3) for b in (10, 20, 30)}
    vals[(2, 20)] = -0.1
    assert parameter_stability(full_grid(vals), SPACE).isolated_peak is False


# --------------------------------------------------------------- cost stress


def test_cost_stress_scales_spread_slippage_and_commission() -> None:
    seen: list[tuple[float, float, Decimal]] = []

    def run(cfg: BacktestConfig, start: datetime, end: datetime) -> BacktestResult:
        seen.append(
            (cfg.costs.spread_pips, cfg.costs.slippage_pips, cfg.costs.commission_per_lot_side)
        )
        return mk_result(cfg, start, end, [0.5, -0.2] * 15)

    rows = cost_stress(BASE, run, Window(T0, T0 + timedelta(days=30)))
    assert [r.multiplier for r in rows] == [1.0, 1.5, 2.0, 3.0]
    assert [r.spread_pips for r in rows] == pytest.approx([1.0, 1.5, 2.0, 3.0])
    assert [r.slippage_pips for r in rows] == pytest.approx([0.2, 0.3, 0.4, 0.6])
    assert [s[2] for s in seen] == [D("3.50"), D("5.250"), D("7.000"), D("10.500")]
    assert all(r.trades == 30 for r in rows)


# --------------------------------------------------------------- monte carlo


def trades_from(rs: list[float]) -> tuple[Trade, ...]:
    return mk_result(BASE, T0, T0 + timedelta(days=30), rs).trades


def test_monte_carlo_withheld_below_ten_trades() -> None:
    """Resampling nine trades would manufacture confidence out of nothing."""
    mc = monte_carlo(trades_from([1.0] * 9), D("1000"), D("1"))
    assert mc.final_return_pct is None and mc.max_drawdown_pct is None
    assert mc.prob_ruin is None and mc.prob_loss is None
    assert mc.note == "insufficient_trades"
    assert "iid_trade_order_shuffle" in mc.assumptions


def test_monte_carlo_is_reproducible_and_discloses_assumptions() -> None:
    ts = trades_from([1.5, -1.0, 0.5, -1.0, 2.0, -1.0, 0.3, -1.0, 1.0, -1.0, 0.8, -1.0])
    a = monte_carlo(ts, D("1000"), D("1"), iterations=200)
    b = monte_carlo(ts, D("1000"), D("1"), iterations=200)
    assert a == b
    assert a.assumptions == (
        "iid_trade_order_shuffle",
        "fixed_fractional_compounding",
        "r_multiples_from_history",
    )
    assert a.note is None


def test_monte_carlo_percentiles_are_ordered_and_final_return_is_order_invariant() -> None:
    """Reordering keeps the product of growth factors, so every path ends at the
    same equity; only the drawdown differs between paths."""
    ts = trades_from([2.0, -1.0, 1.0, -1.0, 0.5, -1.0, 1.5, -1.0, 2.0, -1.0, 0.7, -1.0])
    mc = monte_carlo(ts, D("1000"), D("2"), iterations=300)
    assert mc.final_return_pct is not None and mc.max_drawdown_pct is not None
    f, d = mc.final_return_pct, mc.max_drawdown_pct
    assert f.p5 == pytest.approx(f.p95)
    assert d.p5 <= d.p25 <= d.p50 <= d.p75 <= d.p95
    expected = 1.0
    for r in (2.0, -1.0, 1.0, -1.0, 0.5, -1.0, 1.5, -1.0, 2.0, -1.0, 0.7, -1.0):
        expected *= 1 + r * 2 / 100
    assert f.p50 == pytest.approx((expected - 1) * 100)


def test_monte_carlo_all_winners_never_lose_or_ruin() -> None:
    mc = monte_carlo(trades_from([1.0] * 12), D("1000"), D("1"), iterations=50)
    assert mc.prob_loss == 0.0 and mc.prob_ruin == 0.0


def test_monte_carlo_ruin_counts_paths_reaching_the_drawdown() -> None:
    """All -1R at 10% risk loses ~65% over 10 trades, past the 50% ruin line."""
    mc = monte_carlo(trades_from([-1.0] * 10), D("1000"), D("10"), iterations=50)
    assert mc.prob_ruin == 1.0 and mc.prob_loss == 1.0


def test_monte_carlo_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        monte_carlo(trades_from([1.0] * 12), D("0"), D("1"))
    with pytest.raises(ValueError):
        monte_carlo(trades_from([1.0] * 12), D("1000"), D("0"))


# ----------------------------------------------------------------- bootstrap


def test_bootstrap_withheld_below_twenty_observations() -> None:
    ci = bootstrap_ci([1.0] * 19)
    assert ci.low is None and ci.high is None
    assert ci.note == "insufficient_observations" and ci.n == 19
    assert ci.estimate == 1.0


def test_bootstrap_empty_input_has_no_estimate() -> None:
    ci = bootstrap_ci([])
    assert ci.estimate is None and ci.n == 0 and ci.note == "insufficient_observations"


def test_bootstrap_interval_brackets_estimate_and_is_reproducible() -> None:
    vals = [(-1.0 if i % 3 == 0 else 1.0) * (1 + (i % 4) * 0.1) for i in range(60)]
    a = bootstrap_ci(vals, iterations=500)
    assert a == bootstrap_ci(vals, iterations=500)
    assert a.low is not None and a.high is not None and a.estimate is not None
    assert a.low <= a.estimate <= a.high
    assert a.note is None
    assert bootstrap_ci(vals, iterations=500, seed=99) != a


def test_bootstrap_constant_values_have_zero_width() -> None:
    ci = bootstrap_ci([0.5] * 30, iterations=100)
    assert ci.low == ci.high == ci.estimate == 0.5


def test_bootstrap_accepts_a_custom_statistic() -> None:
    vals = [float(i) for i in range(40)]
    ci = bootstrap_ci(vals, iterations=200, statistic=lambda v: statistics.median(v))
    assert ci.estimate == statistics.median(vals)


def test_bootstrap_wider_confidence_is_wider() -> None:
    vals = [float((i * 7) % 11) for i in range(50)]
    n95 = bootstrap_ci(vals, iterations=400, confidence=0.95)
    n80 = bootstrap_ci(vals, iterations=400, confidence=0.80)
    assert n95.low is not None and n95.high is not None
    assert n80.low is not None and n80.high is not None
    assert n95.high - n95.low >= n80.high - n80.low


# -------------------------------------------------------------------- regimes


def make_candles() -> list[Candle]:
    """600 five-minute bars: rise for 300, fall for 300 at the same speed; narrow
    range until bar 450, then a five-times wider one.

    The fall must match the rise: a faster fall widens true range (it spans the
    gap from the previous close), which would make bar 400 high-volatility for
    a reason the test is not about."""
    out: list[Candle] = []
    price = 1.0
    for i in range(600):
        price += 0.0002 if i < 300 else -0.0002
        rng = 0.0002 if i < 450 else 0.0010
        out.append(
            Candle(
                T0 + timedelta(minutes=5 * i), price, price + rng / 2, price - rng / 2, price
            )
        )
    return out


def entry_at(candles: list[Candle], idx: int) -> datetime:
    return candles[idx].open_time


def test_regime_trend_and_volatility_classified_from_prior_candles_only() -> None:
    cs = make_candles()
    trades = (
        mk_trade(1, 1.0, entry_at(cs, 250)),  # uptrend, narrow bars
        mk_trade(2, -1.0, entry_at(cs, 400)),  # downtrend (falling 100 bars), narrow
        mk_trade(3, 2.0, entry_at(cs, 500)),  # downtrend, wide bars -> high_vol
        mk_trade(4, 0.5, entry_at(cs, 20)),  # no 200-bar history
    )
    res = BacktestResult(BASE, T0, T0 + timedelta(days=1), 600, trades, (), (), D("1000"))
    rows = {r.regime: r for r in regime_breakdown(res, cs)}
    assert rows["uptrend"].trades == 1
    assert rows["downtrend"].trades == 2
    assert rows["trend_unclassified"].trades == 1
    assert rows["high_vol"].trades == 1 and rows["high_vol"].expectancy_r == pytest.approx(2.0)
    assert rows["low_vol"].trades == 2
    assert rows["vol_unclassified"].trades == 1
    assert rows["downtrend"].win_rate_pct == pytest.approx(50.0)
    assert rows["downtrend"].net_pnl == D("10.00")


def test_regime_each_trade_appears_once_per_dimension() -> None:
    cs = make_candles()
    trades = tuple(mk_trade(i, 0.1, entry_at(cs, 250 + 5 * i)) for i in range(20))
    res = BacktestResult(BASE, T0, T0 + timedelta(days=1), 600, trades, (), (), D("1000"))
    rows = regime_breakdown(res, cs)
    trend = sum(
        r.trades for r in rows if r.regime in ("uptrend", "downtrend", "trend_unclassified")
    )
    vol = sum(
        r.trades for r in rows if r.regime in ("high_vol", "low_vol", "vol_unclassified")
    )
    year = sum(r.trades for r in rows if r.regime.startswith("year_"))
    assert trend == vol == year == 20


def test_regime_ignores_the_candle_at_entry_time() -> None:
    """Classification may only use information from before the entry; the
    entry bar's own prices are not known when the decision is made."""
    cs = make_candles()
    t = mk_trade(1, 1.0, entry_at(cs, 250))
    res = BacktestResult(BASE, T0, T0 + timedelta(days=1), 600, (t,), (), (), D("1000"))
    before = regime_breakdown(res, cs)
    tampered = list(cs)
    c = tampered[250]
    tampered[250] = Candle(c.open_time, c.open, 50.0, 0.0001, 0.0001)
    assert regime_breakdown(res, tampered) == before


def test_regime_year_rows_follow_entry_year() -> None:
    cs = make_candles()
    trades = (
        mk_trade(1, 1.0, datetime(2024, 6, 1, tzinfo=UTC)),
        mk_trade(2, 1.0, datetime(2025, 6, 1, tzinfo=UTC)),
        mk_trade(3, -1.0, datetime(2025, 7, 1, tzinfo=UTC)),
    )
    res = BacktestResult(BASE, T0, T0 + timedelta(days=700), 600, trades, (), (), D("1000"))
    years = {r.regime: r for r in regime_breakdown(res, cs) if r.regime.startswith("year_")}
    assert set(years) == {"year_2024", "year_2025"}
    assert years["year_2025"].trades == 2
    assert years["year_2025"].win_rate_pct == pytest.approx(50.0)


def test_regime_with_no_trades_is_empty() -> None:
    res = BacktestResult(BASE, T0, T0 + timedelta(days=1), 600, (), (), (), D("1000"))
    assert regime_breakdown(res, make_candles()) == []


# ------------------------------------------------------------------ baseline


def test_baseline_comparison_against_standing_aside() -> None:
    good = baseline_comparison(metrics_of([2.0, -0.5] * 20))
    assert good["beats_no_trade"] is True
    assert good["expectancy_ci_excludes_zero"] is True
    assert good["excess_return_pct"] == pytest.approx(
        metrics_of([2.0, -0.5] * 20).net_return_pct
    )
    bad = baseline_comparison(metrics_of([-1.0, 0.2] * 20))
    assert bad["beats_no_trade"] is False
    assert bad["expectancy_ci_excludes_zero"] is True  # reliably negative still excludes zero


def test_baseline_comparison_without_enough_trades_makes_no_claim() -> None:
    out = baseline_comparison(metrics_of([1.0] * 5))
    assert out["expectancy_ci_excludes_zero"] is None


def test_no_recommendation_language_in_codes() -> None:
    banned = ("buy", "sell", "consider", "should")
    mc = monte_carlo(trades_from([1.0] * 12), D("1000"), D("1"), iterations=10)
    texts = [*mc.assumptions, "insufficient_trades", "no_eligible_parameters"]
    assert not any(b in t for t in texts for b in banned)
