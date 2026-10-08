"""Meme Lifecycle Lab — trade statistics.

Statistics that overstate are worse than none: profit factor is undefined (not
infinite) with no losses, open positions are not results, and a strategy whose
profit is one trade must say so via top-N contribution.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.lifecycle_lab.domain import (
    AgeBucket,
    Arm,
    DivergenceCase,
    ExitReason,
    LifecycleState,
)
from app.lifecycle_lab.metrics import compute_metrics, percentile
from app.lifecycle_lab.portfolio import PaperTrade, PortfolioSnapshot

pytestmark = pytest.mark.unit

T0 = datetime(2026, 9, 1, tzinfo=UTC)
CAP = Decimal("1000")


def trade(i: int, pnl: str | None, *, hours: int = 1, status: str = "closed") -> PaperTrade:
    p = None if pnl is None else Decimal(pnl)
    return PaperTrade(
        trade_key=f"k{i:03d}",
        arm=Arm.BASELINE,
        meme_id="m",
        mint_address=f"M{i}",
        entry_at=T0 + timedelta(hours=i),
        entry_price=Decimal(1),
        size_usd=Decimal(10),
        quantity=Decimal(10),
        entry_fees_usd=Decimal(0),
        entry_market_cap=None,
        entry_liquidity_usd=None,
        token_age_seconds=None,
        age_bucket=AgeBucket.UNKNOWN,
        lifecycle_state=LifecycleState.UNKNOWN,
        divergence_case=DivergenceCase.NONE,
        entry_reason="conditions_met",
        entry_features={},
        evidence_timeline=(),
        cost_model="flat",
        exit_at=None if p is None else T0 + timedelta(hours=i + hours),
        exit_price=None,
        exit_reason=ExitReason.TAKE_PROFIT if p is not None else ExitReason.END_OF_DATA,
        exit_fees_usd=None,
        pnl_usd=p,
        return_pct=None if p is None else p / Decimal(10) * 100,
        status=status,
    )


def test_profit_factor_is_none_without_losses() -> None:
    """Three wins and no losses have not proven a ratio; ∞ would read as a claim."""
    m = compute_metrics([trade(1, "5"), trade(2, "3")], starting_capital=CAP)
    assert m.profit_factor is None
    assert m.losses == 0 and m.wins == 2
    assert m.win_rate == Decimal(1)


def test_core_stats() -> None:
    trades = [trade(1, "10"), trade(2, "-4"), trade(3, "-2"), trade(4, "6")]
    m = compute_metrics(trades, starting_capital=CAP)
    assert m.trades == 4
    assert m.net_pnl == Decimal("10")
    assert m.profit_factor == Decimal(16) / Decimal(6)
    assert m.expectancy == Decimal("2.5")
    assert m.avg_win == Decimal(8)
    assert m.avg_loss == Decimal(-3)
    assert m.roi == Decimal("0.01")
    assert m.longest_losing_streak == 2
    assert m.avg_holding_seconds == Decimal(3600)
    assert m.median_holding_seconds == Decimal(3600)


def test_open_positions_are_not_results() -> None:
    m = compute_metrics([trade(1, "5"), trade(2, None, status="open")], starting_capital=CAP)
    assert m.trades == 1
    assert m.open_at_end == 1


def test_top_n_contribution_exposes_concentration() -> None:
    """One +100 winner among losers: net +80, the top trade is 125% of it."""
    trades = [trade(0, "100"), *[trade(i, "-2") for i in range(1, 11)]]
    m = compute_metrics(trades, starting_capital=CAP)
    assert m.net_pnl == Decimal(80)
    assert m.top_n_contribution["1"] == Decimal(100) / Decimal(80)
    assert m.net_pnl_ex_top_n["1"] == Decimal(-20)
    assert m.net_pnl_ex_top_n["10"] == Decimal(-2)


def test_top_n_contribution_is_none_when_net_not_positive() -> None:
    m = compute_metrics([trade(1, "-5"), trade(2, "1")], starting_capital=CAP)
    assert m.top_n_contribution == {"1": None, "5": None, "10": None}


def test_percentiles_interpolate_linearly() -> None:
    values = [Decimal(v) for v in (1, 2, 3, 4, 5)]
    assert percentile(values, 50) == Decimal(3)
    assert percentile(values, 25) == Decimal(2)
    assert percentile(values, 90) == Decimal("4.6")
    assert percentile([], 50) is None
    trades = [trade(i, str(i)) for i in range(1, 6)]  # returns 10..50 %
    m = compute_metrics(trades, starting_capital=CAP)
    rp = m.return_percentiles
    assert rp["min"] == Decimal(10) and rp["max"] == Decimal(50)
    assert rp["p50"] == Decimal(30) and rp["mean"] == Decimal(30)
    assert rp["p95"] == Decimal(48)


def test_max_drawdown_from_snapshots() -> None:
    def snap(dd: str | None) -> PortfolioSnapshot:
        return PortfolioSnapshot(
            at=T0,
            equity=None if dd is None else CAP,
            cash=CAP,
            deployed=Decimal(0),
            realized_pnl=Decimal(0),
            unrealized_pnl=Decimal(0),
            open_positions=0,
            peak_equity=CAP,
            drawdown=None if dd is None else Decimal(dd),
        )

    m = compute_metrics([], [snap("0.01"), snap(None), snap("0.05")], starting_capital=CAP)
    assert m.max_drawdown == Decimal("0.05")
    assert compute_metrics([], [], starting_capital=CAP).max_drawdown is None


def test_empty_is_insufficient_not_zero() -> None:
    m = compute_metrics([], starting_capital=CAP)
    assert m.trades == 0 and m.win_rate is None and m.expectancy is None
    assert m.sample_label == "INSUFFICIENT_SAMPLE"


def test_flags_propagate_and_to_dict_is_json_safe() -> None:
    t = replace(trade(1, "1"), contains_backfill=True, hindsight=True)
    m = compute_metrics([t], starting_capital=CAP)
    assert m.contains_backfill and m.hindsight
    json.dumps(m.to_dict())
