"""Monthly-target analysis and strategy scorecards.

The properties that matter: a target is never reached by sizing up (the
analysis only reads history), too little history yields None with a reason
rather than a number, and a strategy whose balance rose on negative
expectancy is still flagged — an ending balance is not an edge.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.labs.forex.compare import evaluate, rank
from app.labs.forex.metrics import MonthReturn, compute_metrics
from app.labs.forex.research import StabilityReport
from app.labs.forex.targets import DISCLAIMER_CODES, target_analysis
from app.labs.forex.types import (
    BacktestConfig,
    BacktestResult,
    Direction,
    EquityPoint,
    ExitReason,
    StrategyId,
    Trade,
)

pytestmark = pytest.mark.unit

T0 = datetime(2024, 1, 1, tzinfo=UTC)
D = Decimal


def _trade(i: int, r: float) -> Trade:
    exit_t = T0 + timedelta(hours=6 * i + 1)
    net = D(str(round(r * 10, 2)))
    return Trade(
        id=i,
        direction=Direction.LONG,
        signal_time=exit_t - timedelta(hours=1),
        entry_time=exit_t - timedelta(hours=1),
        exit_time=exit_t,
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
        exit_reason=ExitReason.TAKE_PROFIT if r > 0 else ExitReason.STOP_LOSS,
        reason="t",
    )


def _month(key: str, pct: float) -> MonthReturn:
    return MonthReturn(key, D("1000"), D("1000"), pct, 10, D(0))


def _metrics(rs: list[float]):  # type: ignore[no-untyped-def]
    trades = tuple(_trade(i + 1, r) for i, r in enumerate(rs))
    bal = D("1000") + sum((t.net_pnl for t in trades), D(0))
    curve = (
        EquityPoint(T0, D("1000"), D("1000")),
        *(EquityPoint(t.exit_time, D("1000"), D("1000")) for t in trades),
    )
    res = BacktestResult(
        BacktestConfig(StrategyId.RSI_PULLBACK),
        T0,
        T0 + timedelta(days=60),
        1000,
        trades,
        curve,
        (),
        bal,
    )
    return compute_metrics(res)


# ------------------------------------------------------------------ targets


def test_target_hit_rates_count_history_only() -> None:
    """Historical frequency is a plain count of months at or above the target."""
    months = [_month("2024-01", 12.0), _month("2024-02", -4.0), _month("2024-03", 5.0)]
    trades = [_trade(i, 1.0 if i % 2 else -1.0) for i in range(1, 31)]
    rep = target_analysis(
        months,
        trades,
        initial_capital=D("1000"),
        risk_pct=D("1"),
        max_drawdown_pct=7.5,
        label="full",
    )
    rows = {r.target_pct: r for r in rep.rows}
    assert rows[5.0].months_hit == 2 and rows[5.0].hit_rate_pct == pytest.approx(200 / 3)
    assert rows[10.0].months_hit == 1
    assert rows[100.0].months_hit == 0 and rows[100.0].hit_rate_pct == 0.0
    assert (rep.profitable_months, rep.losing_months) == (2, 1)
    assert rep.best_month_pct == 12.0 and rep.worst_month_pct == -4.0
    assert rep.max_drawdown_pct == 7.5
    for code in DISCLAIMER_CODES:
        assert code in rep.disclaimer_codes


def test_risk_does_not_change_with_the_target() -> None:
    """Raising the target must never raise the simulated risk: size is fixed
    by the caller's risk_pct, so a 100% target cannot buy itself leverage."""
    months = [_month(f"2024-{m:02d}", 1.0) for m in range(1, 7)]
    trades = [_trade(i, 2.0 if i % 3 == 0 else -1.0) for i in range(1, 61)]
    low = target_analysis(
        months,
        trades,
        targets=(5,),
        initial_capital=D("1000"),
        risk_pct=D("1"),
        max_drawdown_pct=5,
        label="a",
    )
    high = target_analysis(
        months,
        trades,
        targets=(100,),
        initial_capital=D("1000"),
        risk_pct=D("1"),
        max_drawdown_pct=5,
        label="a",
    )
    assert low.risk_of_ruin == high.risk_of_ruin


def test_too_few_trades_gives_no_simulation() -> None:
    rep = target_analysis(
        [_month("2024-01", 3.0)],
        [_trade(1, 1.0)],
        initial_capital=D("1000"),
        risk_pct=D("1"),
        max_drawdown_pct=0,
        label="oos",
    )
    assert rep.simulation_note == "insufficient_trades"
    assert all(r.simulated_hit_rate_pct is None for r in rep.rows)
    assert rep.risk_of_ruin.prob_50pct_drawdown is None


def test_target_analysis_is_deterministic() -> None:
    months = [_month("2024-01", 2.0), _month("2024-02", -1.0)]
    trades = [_trade(i, 1.5 if i % 2 else -1.0) for i in range(1, 41)]
    kw: dict[str, object] = {
        "initial_capital": D("1000"),
        "risk_pct": D("2"),
        "max_drawdown_pct": 3.0,
        "label": "x",
    }
    assert target_analysis(months, trades, **kw) == target_analysis(months, trades, **kw)  # type: ignore[arg-type]


# ------------------------------------------------------------------ compare


def test_balance_up_on_negative_expectancy_is_still_flagged() -> None:
    """Ending balance can rise while expectancy is negative (e.g. a rounding
    of costs); the scorecard reads expectancy, never the balance."""
    m = _metrics([-0.2] * 40)
    m = dataclasses.replace(m, ending_balance=D("1100"), net_return_pct=10.0)
    card = evaluate(
        "x", full=m, development=None, out_of_sample=None, stressed=None, stability=None
    )
    assert "negative_expectancy" in card.flags
    assert card.verdict_code == "no_edge_detected"


def test_insufficient_trades_is_inconclusive_and_unscored() -> None:
    m = _metrics([1.0, -0.5, 1.0])
    card = evaluate("x", full=m, development=None, out_of_sample=m, stressed=m, stability=None)
    assert "insufficient_trades" in card.flags
    assert card.robustness_score is None
    assert card.verdict_code == "inconclusive"


def test_poor_out_of_sample_and_overfitting_flags() -> None:
    dev = _metrics([1.0, -0.5] * 30)
    oos = _metrics([-1.0, 0.5] * 15)
    iso = StabilityReport({"p": 1}, 4, 25.0, 3.0, True, 10.0)
    card = evaluate(
        "x", full=dev, development=dev, out_of_sample=oos, stressed=dev, stability=iso
    )
    assert "poor_out_of_sample" in card.flags
    assert "possible_overfitting" in card.flags
    assert card.verdict_code == "no_edge_detected"


def test_cost_sensitivity_flag() -> None:
    full = _metrics([1.0, -0.5] * 30)
    stressed = _metrics([0.5, -1.0] * 30)
    card = evaluate(
        "x", full=full, development=full, out_of_sample=full, stressed=stressed, stability=None
    )
    assert "cost_sensitive" in card.flags


def test_no_verdict_ever_says_profitable() -> None:
    full = _metrics([1.0, -0.5] * 40)
    card = evaluate(
        "x",
        full=full,
        development=full,
        out_of_sample=full,
        stressed=full,
        stability=StabilityReport({}, 4, 100.0, 1.0, False, 90.0),
    )
    assert card.verdict_code in {"candidate_edge", "inconclusive", "no_edge_detected"}
    assert "profit" not in card.verdict_code


def test_rank_orders_by_robustness_with_unscored_last() -> None:
    good = _metrics([1.0, -0.5] * 40)
    weak = _metrics([0.6, -0.5] * 40)
    few = _metrics([1.0])
    cards = [
        evaluate(
            "c_few",
            full=few,
            development=None,
            out_of_sample=None,
            stressed=None,
            stability=None,
        ),
        evaluate(
            "b_weak",
            full=weak,
            development=weak,
            out_of_sample=weak,
            stressed=weak,
            stability=None,
        ),
        evaluate(
            "a_good",
            full=good,
            development=good,
            out_of_sample=good,
            stressed=good,
            stability=None,
        ),
    ]
    assert [c.name for c in rank(cards)] == ["a_good", "b_weak", "c_few"]
