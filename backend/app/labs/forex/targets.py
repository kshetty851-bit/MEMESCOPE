"""Monthly-target analysis: how often did the HISTORY reach a monthly return,
and what do resampled months say about the spread of outcomes.

This is an observation of the past, not a forecast, and it never scales risk
to reach a target: every simulation uses the risk percent the run was made
with. A target is a threshold to count against, not a goal to size toward.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.labs.forex.metrics import MonthReturn
from app.labs.forex.research import compound_path
from app.labs.forex.rng import Rng
from app.labs.forex.types import Trade

MIN_TRADES_FOR_SIMULATION = 10
RUIN_HORIZON_MONTHS = 12
_RUIN_DD_PCT = 50.0
#: "Lost all risk capital" = equity below this fraction of the start.
_RISK_CAPITAL_FLOOR = 0.10

DISCLAIMER_CODES = (
    "historical_observation_not_forecast",
    "no_position_size_increase_to_force_target",
    "risk_of_ruin_assumes_iid_trades",
)
RUIN_ASSUMPTIONS = (
    "iid_trade_resampling",
    "fixed_fractional_compounding",
    "r_multiples_from_history",
    "historical_average_monthly_trade_count",
)


@dataclass(frozen=True, slots=True)
class TargetRow:
    target_pct: float
    months_hit: int
    hit_rate_pct: float | None
    simulated_hit_rate_pct: float | None


@dataclass(frozen=True, slots=True)
class RuinEstimate:
    prob_50pct_drawdown: float | None
    prob_lose_all_risk_capital: float | None
    horizon_months: int
    iterations: int
    assumptions: tuple[str, ...]
    note: str | None = None


@dataclass(frozen=True, slots=True)
class TargetReport:
    label: str
    months_total: int
    profitable_months: int
    losing_months: int
    best_month_pct: float | None
    worst_month_pct: float | None
    max_drawdown_pct: float
    rows: list[TargetRow]
    risk_of_ruin: RuinEstimate
    disclaimer_codes: tuple[str, ...]
    #: "insufficient_trades" when too little history to resample.
    simulation_note: str | None = None


def _draw_month(rs: Sequence[float], n: int, rng: Rng) -> list[float]:
    return [rs[rng.randrange(len(rs))] for _ in range(n)]


def target_analysis(
    months: Sequence[MonthReturn],
    trades: Sequence[Trade],
    *,
    targets: Sequence[float] = (5, 10, 20, 50, 100),
    initial_capital: Decimal,
    risk_pct: Decimal,
    max_drawdown_pct: float,
    seed: int = 3,
    iterations: int = 2000,
    label: str,
) -> TargetReport:
    if initial_capital <= 0 or risk_pct <= 0 or iterations < 1:
        raise ValueError("invalid_target_inputs")
    total = len(months)
    rets = [m.return_pct for m in months]
    rs = [t.r_multiple for t in trades]
    risk = float(risk_pct)

    per_month = round(len(rs) / total) if total else 0
    can_simulate = len(rs) >= MIN_TRADES_FOR_SIMULATION and per_month >= 1
    rng = Rng(seed)

    sim_returns: list[float] = []
    if can_simulate:
        for _ in range(iterations):
            final, _dd, _low = compound_path(_draw_month(rs, per_month, rng), risk)
            sim_returns.append((final - 1.0) * 100.0)

    rows: list[TargetRow] = []
    for tgt in targets:
        hit = sum(1 for r in rets if r >= tgt)
        rows.append(
            TargetRow(
                target_pct=float(tgt),
                months_hit=hit,
                hit_rate_pct=hit / total * 100 if total else None,
                simulated_hit_rate_pct=(
                    sum(1 for r in sim_returns if r >= tgt) / iterations * 100
                    if can_simulate
                    else None
                ),
            )
        )

    if can_simulate:
        dd_hits = floor_hits = 0
        for _ in range(iterations):
            path = _draw_month(rs, per_month * RUIN_HORIZON_MONTHS, rng)
            _final, dd, low = compound_path(path, risk)
            dd_hits += dd >= _RUIN_DD_PCT
            floor_hits += low < _RISK_CAPITAL_FLOOR
        ruin = RuinEstimate(
            dd_hits / iterations,
            floor_hits / iterations,
            RUIN_HORIZON_MONTHS,
            iterations,
            RUIN_ASSUMPTIONS,
        )
    else:
        ruin = RuinEstimate(
            None,
            None,
            RUIN_HORIZON_MONTHS,
            iterations,
            RUIN_ASSUMPTIONS,
            "insufficient_trades",
        )

    return TargetReport(
        label=label,
        months_total=total,
        profitable_months=sum(1 for r in rets if r > 0),
        losing_months=sum(1 for r in rets if r < 0),
        best_month_pct=max(rets) if rets else None,
        worst_month_pct=min(rets) if rets else None,
        max_drawdown_pct=max_drawdown_pct,
        rows=rows,
        risk_of_ruin=ruin,
        disclaimer_codes=DISCLAIMER_CODES,
        simulation_note=None if can_simulate else "insufficient_trades",
    )
