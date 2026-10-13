from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from heapq import heappop, heappush
from .config import AppConfig
from .model import ModelBundle
from .models import Opportunity
from .scoring import score_many

@dataclass
class PortfolioResult:
    strategy: str
    trades: int
    wins: int
    losses: int
    net_pnl_usd: float
    final_cash_usd: float
    max_realized_drawdown_usd: float
    average_pnl_usd: float | None
    capacity_blocked: int
    untestable: int

def _simulate(rows: list[Opportunity], selected: set[str], name: str, config: AppConfig) -> PortfolioResult:
    cfg = config.backtest
    cash = cfg.starting_cash_usd; open_heap = []; open_cost = 0.0
    pnls = []; equity_curve = [cash]; capacity_blocked = 0; untestable = 0
    def close_until(ts):
        nonlocal cash, open_cost
        while open_heap and open_heap[0][0] <= ts:
            _, _, cost, proceeds = heappop(open_heap)
            open_cost -= cost; cash += proceeds; pnls.append(proceeds-cost); equity_curve.append(cash + open_cost)
    for op in sorted(rows, key=lambda x: (x.decision_ts, x.mint, x.opportunity_id)):
        close_until(op.decision_ts)
        if op.opportunity_id not in selected: continue
        out = op.outcome
        if not out or out.unresolved or not out.all_costs_included:
            untestable += 1; continue
        cost = out.matched_size_entry_cost_usd
        if abs(cost - cfg.expected_all_in_entry_cost_usd) > cfg.entry_cost_tolerance_usd:
            untestable += 1; continue
        equity_cost_basis = cash + open_cost
        allowed_exposure = min(cfg.maximum_gross_cost_exposure_usd, cfg.maximum_equity_exposure_fraction*equity_cost_basis)
        if len(open_heap) >= cfg.maximum_open_positions or open_cost + cost > allowed_exposure + 1e-9 or cash < cost:
            capacity_blocked += 1; continue
        cash -= cost; open_cost += cost
        heappush(open_heap, (out.exit_ts, op.opportunity_id, cost, out.matched_size_exit_proceeds_usd))
    close_until(max((x[0] for x in open_heap), default=rows[-1].decision_ts if rows else None))
    while open_heap:
        _, _, cost, proceeds = heappop(open_heap); open_cost -= cost; cash += proceeds; pnls.append(proceeds-cost); equity_curve.append(cash+open_cost)
    peak = equity_curve[0]; max_dd = 0.0
    for x in equity_curve:
        peak = max(peak, x); max_dd = max(max_dd, peak-x)
    return PortfolioResult(name, len(pnls), sum(p>0 for p in pnls), sum(p<0 for p in pnls), round(sum(pnls),6), round(cash,6), round(max_dd,6), None if not pnls else round(sum(pnls)/len(pnls),6), capacity_blocked, untestable)

def run_selection_backtest(rows: list[Opportunity], config: AppConfig, bundle: ModelBundle | None = None) -> dict:
    if len({o.opportunity_id for o in rows}) != len(rows):
        raise ValueError("duplicate opportunity_id in backtest")
    if bundle:
        boundary = datetime.fromisoformat(bundle.training_range.get('labels_available_end', bundle.training_range['train_end']))
        boundary += timedelta(minutes=config.training.split.embargo_minutes)
        if any(o.decision_ts <= boundary for o in rows):
            raise ValueError("backtest rows overlap training/label embargo; supply later held-out rows")
    scored = score_many(rows, config, bundle)
    baseline_ids = {o.opportunity_id for o in rows if o.baseline_eligible}
    accepted = {s.opportunity_id for s in scored if s.decision in config.backtest.accept_decisions}
    ai_ids = baseline_ids & accepted
    base = _simulate(rows, baseline_ids, "existing_strategy_control", config)
    ai = _simulate(rows, ai_ids, "pretrade_ai_gate_plus_existing_strategy", config)
    by_id = {o.opportunity_id:o for o in rows}
    skipped = baseline_ids - ai_ids
    skipped_pnls = [by_id[i].outcome.net_pnl_usd for i in skipped if by_id[i].outcome and not by_id[i].outcome.unresolved and by_id[i].outcome.all_costs_included]
    return {
        "scope": "offline selection-only comparison; entries/exits and matched-size outcomes are otherwise identical",
        "warning": "Results describe the supplied dataset only. No live-trading or forward-performance claim is made.",
        "baseline": base.__dict__, "ai_gated": ai.__dict__,
        "paired_difference": {"net_pnl_usd": round(ai.net_pnl_usd-base.net_pnl_usd,6), "max_realized_drawdown_usd": round(ai.max_realized_drawdown_usd-base.max_realized_drawdown_usd,6), "trades": ai.trades-base.trades},
        "selection_errors": {"skipped_profitable_outcomes": sum(p>0 for p in skipped_pnls), "skipped_losing_outcomes": sum(p<0 for p in skipped_pnls), "forgone_net_pnl_usd_before_capacity_interactions": round(sum(skipped_pnls),6)},
        "score_decisions": {k: sum(s.decision==k for s in scored) for k in ["ACCEPT","REVIEW","REJECT","INSUFFICIENT_DATA"]},
    }
