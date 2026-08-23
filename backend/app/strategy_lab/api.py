"""`/api/v1/strategy-lab` — research surfaces. **Read-only. No write endpoint.**

Every route here answers a question about what a published rule did over stored
observations. None of them opens a position, changes a wallet, or reaches a
chain. There is deliberately no POST, PUT, PATCH or DELETE on this router: a
research surface that could be written to is a control surface.

The one thing that runs work — the historical replay — is invoked by the
scheduler or by an operator on the host, never by an HTTP request, so a page
load can never kick off a several-minute job.

While `STRATEGY_LAB_MODE` is `DISABLED` the routes still answer and report
`state: DISABLED`, rather than 404ing or serving an empty board. "Not switched
on here" and "these strategies did nothing" are different facts, and only the
second is a result.

Nothing served here is advice, and no figure here is a real balance. Every
wallet is simulated and every route says so in its payload.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.core.config import settings
from app.models.strategy_lab import (
    StrategyLabOpportunity,
    StrategyLabPosition,
)
from app.strategy_lab import execution, metrics, reporting, rules, service
from app.strategy_lab.state import LabState
from app.strategy_lab.strategies import (
    ALL,
    BY_ID,
    S3_S10_EQUIVALENCE,
    S9_GATE_LIMITATION,
)

router = APIRouter(prefix="/strategy-lab", tags=["strategy-lab"])

#: Shown on every surface. Not decoration — it is the one claim the whole
#: subsystem makes about itself.
BANNER = "Research Only — No Capital Execution"

WINDOWS: dict[str, timedelta | None] = {
    "TODAY": None,  # resolved against the UTC day boundary, not a duration
    "24H": timedelta(hours=24),
    "3D": timedelta(days=3),
    "7D": timedelta(days=7),
    "30D": timedelta(days=30),
    "ALL": None,
}

WINDOW_NOTE = (
    "A window filters the trade set by entry time and restates equity as what "
    "those trades did to a fresh $1,000. It is NOT a re-simulation with that "
    "window's own capital constraints, and it is not the wallet's balance."
)


def _since(window: str, now: datetime) -> datetime | None:
    if window == "ALL":
        return None
    if window == "TODAY":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    delta = WINDOWS.get(window)
    return None if delta is None else now - delta


def _d(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _moonshots(row: metrics.Row) -> list[dict[str, Any]]:
    return [
        {
            "level": float(m.level),
            "reached": m.reached,
            "captured": m.captured,
            "opportunity_usd": _d(m.opportunity_usd),
            "realised_usd": _d(m.realised_usd),
            "efficiency_pct": _d(m.efficiency_pct),
        }
        for m in row.moonshots
    ]


def _row_out(row: metrics.Row, rank: int) -> dict[str, Any]:
    r = row.robustness
    i = row.rug_impact
    return {
        "rank": rank,
        "strategy_id": row.strategy_id,
        "version": row.version,
        "name": row.name,
        "definition_hash": row.definition_hash,
        "benchmark": row.benchmark,
        "n": row.n,
        "offered": row.offered,
        "starting_capital": _d(row.starting_capital),
        "final_equity": _d(row.final_equity),
        "net_pnl": _d(row.net_pnl),
        "gross_pnl": _d(row.gross_pnl),
        "total_costs": _d(row.total_costs),
        "wallet_return_pct": _d(row.wallet_return_pct),
        "profit_factor": _d(row.profit_factor),
        "expectancy": _d(row.expectancy),
        "win_rate_pct": _d(row.win_rate_pct),
        "median_trade_return_pct": _d(row.median_trade_return_pct),
        "mean_trade_return_pct": _d(row.mean_trade_return_pct),
        "max_drawdown_pct": _d(row.max_drawdown_pct),
        "rug_loss_usd": _d(row.rug_loss_usd),
        "rugs": row.rugs,
        "blocked": row.blocked,
        "blocked_for_cash": row.blocked_for_cash,
        "capital_blocked_usd": _d(row.capital_blocked_usd),
        "capture_pct": _d(row.capture_pct),
        "avg_concurrency": _d(row.avg_concurrency),
        "peak_concurrency": row.peak_concurrency,
        "avg_hold_minutes": _d(row.avg_hold_minutes),
        "unsettled": row.unsettled,
        "day_concentration_pct": _d(row.day_concentration_pct),
        "moonshots": _moonshots(row),
        "lab_score": _d(row.lab_score),
        "score_components": {
            "robust_return_pct": _d(row.score_r),
            "drawdown": _d(row.score_d),
            "sample_shrink": _d(row.score_s),
            "profit_factor_multiplier": _d(row.score_p),
        },
        "robustness": {
            "normal_pnl": _d(r.normal_pnl),
            "ex_best_1_pnl": _d(r.ex_best_1_pnl),
            "ex_best_3_pnl": _d(r.ex_best_3_pnl),
            "ex_worst_1_pnl": _d(r.ex_worst_1_pnl),
            "ex_worst_3_pnl": _d(r.ex_worst_3_pnl),
            "top_1_share_pct": _d(r.top_1_share_pct),
            "top_3_share_pct": _d(r.top_3_share_pct),
            "top_5_share_pct": _d(r.top_5_share_pct),
            "outlier_dependent": r.outlier_dependent,
        },
        "rug_impact": {
            "count": i.count,
            "capital_invested": _d(i.capital_invested),
            "capital_recovered_before": _d(i.capital_recovered_before),
            "residual_recovered": _d(i.residual_recovered),
            "net_loss": _d(i.net_loss),
            "reached_125": i.reached_125,
            "reached_150": i.reached_150,
            "reached_175": i.reached_175,
            "reached_200": i.reached_200,
        },
        "flags": list(row.flags),
    }


async def _books(session: DbSession, *, mode: str, since: datetime | None):
    run_id = None
    if mode == LabState.BACKTEST.value:
        run = await reporting.latest_run(session)
        if run is None:
            return [], None
        run_id = run.id
        books = await reporting.load_books(session, mode=mode, run_id=run_id, since=since)
        return books, run
    return await reporting.load_books(session, mode=mode, since=since), None


def _mode_param(mode: str) -> str:
    if mode not in (LabState.BACKTEST.value, LabState.FORWARD_RESEARCH.value):
        raise HTTPException(422, f"mode must be BACKTEST or FORWARD_RESEARCH, got {mode!r}")
    return mode


@router.get("/overview")
async def overview(
    session: DbSession,
    mode: Annotated[str, Query()] = LabState.BACKTEST.value,
) -> dict[str, Any]:
    """The header figures. Everything here is simulated; nothing is a balance."""
    mode = _mode_param(mode)
    state = service.current_state()
    books, run = await _books(session, mode=mode, since=None)
    rows = metrics.rank([b.row for b in books])

    evaluated = (
        await session.execute(select(func.count()).select_from(StrategyLabOpportunity))
    ).scalar_one()
    simulated_trades = (
        await session.execute(select(func.count()).select_from(StrategyLabPosition))
    ).scalar_one()

    def best(key, only_scored: bool = True):
        pool = [r for r in rows if r.n > 0] if only_scored else rows
        return None if not pool else max(pool, key=key)

    lowest_dd = min(
        (r for r in rows if r.n > 0), key=lambda r: r.max_drawdown_pct, default=None
    )
    best_moon = best(
        lambda r: (
            (r.moonshot(Decimal(2)).efficiency_pct or Decimal(-1))
            if r.moonshot(Decimal(2))
            else Decimal(-1)
        )
    )

    return {
        "title": "STRATEGY LAB",
        "banner": BANNER,
        "state": state.value,
        "mode": mode,
        "forward_research_active": state is LabState.FORWARD_RESEARCH,
        "simulated_capital_notice": (
            "Every balance shown in Strategy Lab is SIMULATED research capital. "
            "No paper position, no real position, and no transaction is created "
            "by anything on this page."
        ),
        "tokens_evaluated": evaluated,
        "strategies_running": len(ALL),
        "simulated_trades": simulated_trades,
        "best_7d": _headline(await _window_leader(session, mode, "7D")),
        "best_30d": _headline(await _window_leader(session, mode, "30D")),
        "lowest_drawdown": _headline(lowest_dd),
        "highest_moonshot_capture": _headline(best_moon),
        "dataset": _dataset(run),
        "execution_model": {
            "id": execution.EXECUTION_MODEL_ID,
            "disclosure": execution.DISCLOSURE,
            "multi_target_policy": rules.MULTI_TARGET_POLICY,
            "multi_target_policy_text": rules.MULTI_TARGET_POLICY_TEXT,
        },
    }


def _headline(row: metrics.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "strategy_id": row.strategy_id,
        "name": row.name,
        "n": row.n,
        "wallet_return_pct": _d(row.wallet_return_pct),
        "max_drawdown_pct": _d(row.max_drawdown_pct),
        "flags": list(row.flags),
    }


async def _window_leader(session: DbSession, mode: str, window: str) -> metrics.Row | None:
    since = _since(window, datetime.now(UTC))
    books, _ = await _books(session, mode=mode, since=since)
    ranked = metrics.rank([b.row for b in books if b.row.n > 0])
    return ranked[0] if ranked else None


def _dataset(run) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "run_id": str(run.id),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "canonical_version": run.canonical_version,
        "metrics_version": run.metrics_version,
        "from": run.dataset_from.isoformat() if run.dataset_from else None,
        "to": run.dataset_to.isoformat() if run.dataset_to else None,
        "candidates": run.candidates,
        "usable": run.usable,
        "excluded": run.excluded,
        "exclusions": run.exclusions,
        "venues": run.venues,
        "observations": run.observation_count,
    }


@router.get("/leaderboard")
async def leaderboard(
    session: DbSession,
    window: Annotated[str, Query()] = "ALL",
    mode: Annotated[str, Query()] = LabState.BACKTEST.value,
    min_sample: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    """§11's board. Ranked by `lab_score`, never by win rate.

    `min_sample` hides thin records rather than silently down-weighting them.
    The default shows everything, because a strategy that refused almost every
    opportunity is itself a result — S9 exists to produce exactly that finding.
    """
    mode = _mode_param(mode)
    if window not in WINDOWS:
        raise HTTPException(422, f"window must be one of {sorted(WINDOWS)}")

    since = _since(window, datetime.now(UTC))
    books, run = await _books(session, mode=mode, since=since)
    ranked = metrics.rank([b.row for b in books if b.row.n >= min_sample])

    return {
        "banner": BANNER,
        "state": service.current_state().value,
        "mode": mode,
        "window": window,
        "window_note": WINDOW_NOTE,
        "min_sample": min_sample,
        "small_sample_threshold": metrics.SMALL_SAMPLE_N,
        "ranking": (
            "LAB_SCORE = (R / (1 + D)) x S x P — R is wallet return with the "
            "single best trade removed, D is max drawdown, S is min(1, N/100), "
            "P is the clamped profit factor. Every component is shown."
        ),
        "dataset": _dataset(run),
        "rows": [_row_out(row, index + 1) for index, row in enumerate(ranked)],
    }


@router.get("/strategies")
async def strategies_list() -> dict[str, Any]:
    """The definitions themselves, and §21's comparison matrix."""
    return {
        "banner": BANNER,
        "notes": {
            "s9_gate": S9_GATE_LIMITATION,
            "s3_s10": S3_S10_EQUIVALENCE,
            "multi_target": rules.MULTI_TARGET_POLICY_TEXT,
        },
        "strategies": [
            {
                "strategy_id": d.strategy_id,
                "version": d.version,
                "name": d.name,
                "purpose": d.purpose,
                "entry_size_usd": _d(d.entry_size_usd),
                "benchmark": d.benchmark,
                "definition_hash": d.definition_hash,
                "hold_hours": d.rules.hold_for.total_seconds() / 3600,
                "rungs": [
                    {"multiple": _d(r.multiple), "fraction": _d(r.fraction)}
                    for r in d.rules.rungs
                ],
                "runner_fraction": _d(d.rules.runner_fraction),
                "trailing": (
                    None
                    if d.rules.trailing is None
                    else {
                        "drawdown": _d(d.rules.trailing.drawdown),
                        "activation_multiple": _d(d.rules.trailing.activation_multiple),
                        "fraction": _d(d.rules.trailing.fraction),
                    }
                ),
                "decay": [
                    {
                        "at_minutes": rule.at.total_seconds() / 60,
                        "never_exceeded": _d(rule.never_exceeded),
                        "at_or_below": _d(rule.at_or_below),
                    }
                    for rule in d.rules.decay
                ],
                "min_discovery_age_hours": (
                    None
                    if d.min_discovery_age is None
                    else d.min_discovery_age.total_seconds() / 3600
                ),
                "matrix": d.matrix_row(),
            }
            for d in ALL
        ],
    }


@router.get("/strategies/{strategy_id}")
async def strategy_detail(
    session: DbSession,
    strategy_id: str,
    mode: Annotated[str, Query()] = LabState.BACKTEST.value,
    trades: Annotated[int, Query(ge=1, le=200)] = 25,
) -> dict[str, Any]:
    """§13. One strategy's curves, distribution and complete trade lifecycles."""
    mode = _mode_param(mode)
    definition = BY_ID.get(strategy_id)
    if definition is None:
        raise HTTPException(404, f"unknown strategy {strategy_id!r}")

    books, run = await _books(session, mode=mode, since=None)
    book = next((b for b in books if b.wallet.strategy_id == strategy_id), None)
    if book is None:
        return {
            "banner": BANNER,
            "strategy_id": strategy_id,
            "name": definition.name,
            "state": service.current_state().value,
            "has_results": False,
            "dataset": _dataset(run),
        }

    result = book.result
    positions = result.positions
    by_pnl = sorted(positions, key=lambda p: p.net_pnl, reverse=True)
    by_time = sorted(positions, key=lambda p: p.opened_at, reverse=True)

    ci = metrics.bootstrap_mean_ci([p.net_pnl for p in positions])
    return {
        "banner": BANNER,
        "state": service.current_state().value,
        "mode": mode,
        "strategy_id": strategy_id,
        "name": definition.name,
        "version": definition.version,
        "purpose": definition.purpose,
        "has_results": True,
        "row": _row_out(book.row, 0),
        "wallet": {
            "simulated": True,
            "starting_balance": _d(book.wallet.starting_balance),
            "cash": _d(book.wallet.cash),
            "peak_equity": _d(book.wallet.peak_equity),
            "open_positions": sum(1 for p in positions if p.closed_at is None),
            "closed_positions": sum(1 for p in positions if p.closed_at is not None),
        },
        "equity_curve": [
            {"at": at.isoformat(), "equity": _d(value)} for at, value in result.equity_curve
        ],
        "daily_pnl": [
            {"day": d.day, "pnl": _d(d.pnl), "trades": d.trades}
            for d in metrics.daily_pnl(result)
        ],
        "distribution": _distribution(positions),
        "mean_pnl_ci95": None if ci is None else [_d(ci[0]), _d(ci[1])],
        "best_trades": [_trade(p) for p in by_pnl[:trades]],
        "worst_trades": [_trade(p) for p in by_pnl[-trades:][::-1]],
        "recent_trades": [_trade(p) for p in by_time[:trades]],
        "blocked": [
            {
                "mint_address": m.mint_address,
                "at": m.at.isoformat(),
                "reason": m.reason,
                "cash_at_refusal": _d(m.cash_at_refusal),
                "peak_multiple": _d(m.peak_multiple),
            }
            for m in sorted(result.missed, key=lambda m: m.at, reverse=True)[:trades]
        ],
        "dataset": _dataset(run),
    }


def _distribution(positions) -> dict[str, int]:
    buckets = {
        "loss_90_100": 0,
        "loss_50_90": 0,
        "loss_0_50": 0,
        "gain_0_50": 0,
        "gain_50_100": 0,
        "gain_100_400": 0,
        "gain_400_plus": 0,
    }
    for p in positions:
        r = p.return_pct
        if r <= -90:
            buckets["loss_90_100"] += 1
        elif r <= -50:
            buckets["loss_50_90"] += 1
        elif r < 0:
            buckets["loss_0_50"] += 1
        elif r < 50:
            buckets["gain_0_50"] += 1
        elif r < 100:
            buckets["gain_50_100"] += 1
        elif r < 400:
            buckets["gain_100_400"] += 1
        else:
            buckets["gain_400_plus"] += 1
    return buckets


def _trade(position) -> dict[str, Any]:
    """One position's complete lifecycle, every fill in order."""
    return {
        "mint_address": position.mint_address,
        "opened_at": position.opened_at.isoformat(),
        "closed_at": position.closed_at.isoformat() if position.closed_at else None,
        "entry_price": str(position.entry_price),
        "size_usd": _d(position.size_usd),
        "entry_cost": _d(position.entry_cost),
        "entry_liquidity_usd": _d(position.entry_liquidity_usd),
        "venue": position.venue,
        "gross_pnl": _d(position.gross_pnl),
        "net_pnl": _d(position.net_pnl),
        "return_pct": _d(position.return_pct),
        "observed_peak_multiple": _d(position.observed_peak_multiple),
        "executable_peak_multiple": _d(position.executable_peak_multiple),
        "terminal_multiple": _d(position.terminal_multiple),
        "final_reason": position.final_reason,
        "unsettled": position.unsettled,
        "catastrophic": position.is_catastrophic,
        "banked_before_final": _d(position.banked_before_final),
        "fills": [
            {
                "at": fill.at.isoformat(),
                "reason": str(fill.reason),
                "price_usd": str(fill.price_usd),
                "multiple": _d(fill.price_usd / position.entry_price),
                "quantity_pct_of_initial": _d(fill.quantity / position.initial_quantity * 100),
                "gross_proceeds": _d(fill.gross_proceeds),
                "execution_cost": _d(cost),
                "net_proceeds": _d(net),
                "rungs_covered": list(fill.rung_indexes),
                "liquidity_usd": _d(fill.liquidity_usd),
            }
            for fill, net, cost in position.fills
        ],
    }


@router.get("/compare/{mint}")
async def token_compare(
    session: DbSession,
    mint: str,
    mode: Annotated[str, Query()] = LabState.BACKTEST.value,
) -> dict[str, Any]:
    """§14. What every strategy did with one canonical opportunity.

    The point of the whole design: the same token, offered to all of them, so
    a leaderboard position can be explained rather than merely observed.
    """
    mode = _mode_param(mode)
    opportunity = await reporting.opportunity_by_mint(session, mint)
    if opportunity is None:
        raise HTTPException(404, f"no canonical opportunity for {mint!r}")

    books, run = await _books(session, mode=mode, since=None)
    outcomes = []
    for book in books:
        position = next((p for p in book.result.positions if p.mint_address == mint), None)
        if position is not None:
            outcomes.append(
                {
                    "strategy_id": book.wallet.strategy_id,
                    "taken": True,
                    "return_pct": _d(position.return_pct),
                    "net_pnl": _d(position.net_pnl),
                    "final_reason": position.final_reason,
                    "fills": len(position.fills),
                    "banked_before_final": _d(position.banked_before_final),
                    "trade": _trade(position),
                }
            )
            continue
        refusal = next((m for m in book.result.missed if m.mint_address == mint), None)
        outcomes.append(
            {
                "strategy_id": book.wallet.strategy_id,
                "taken": False,
                "blocked_reason": refusal.reason if refusal else "NOT_OFFERED",
                "cash_at_refusal": _d(refusal.cash_at_refusal) if refusal else None,
            }
        )

    return {
        "banner": BANNER,
        "mint_address": mint,
        "opportunity": {
            "eligible_at": opportunity.eligible_at.isoformat(),
            "entry_price": str(opportunity.entry_price) if opportunity.entry_price else None,
            "liquidity_usd": _d(opportunity.liquidity_usd),
            "market_cap": _d(opportunity.market_cap),
            "liq_to_mcap": _d(opportunity.liq_to_mcap),
            "volume_24h": _d(opportunity.volume_24h),
            "buys_24h": opportunity.buys_24h,
            "sells_24h": opportunity.sells_24h,
            "venue": opportunity.venue,
            "pool_address": opportunity.pool_address,
            "radar_rank": opportunity.radar_rank,
            "radar_score": _d(opportunity.radar_score),
            "confidence_score": _d(opportunity.confidence_score),
            "risk_band": opportunity.risk_band,
            "security_status": opportunity.security_status,
            "discovery_age_hours": (
                None
                if opportunity.discovery_age_seconds is None
                else float(opportunity.discovery_age_seconds) / 3600
            ),
            "canonical_version": opportunity.canonical_version,
        },
        "outcomes": outcomes,
        "dataset": _dataset(run),
    }


@router.get("/rugs")
async def rug_analysis(
    session: DbSession,
    mode: Annotated[str, Query()] = LabState.BACKTEST.value,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    """§15. Which catastrophes paid something on the way up, and to whom."""
    mode = _mode_param(mode)
    books, run = await _books(session, mode=mode, since=None)
    if not books:
        return {"banner": BANNER, "tokens": [], "by_strategy": [], "dataset": _dataset(run)}

    control = next((b for b in books if b.wallet.strategy_id == "S5"), books[0])
    catastrophes = [p for p in control.result.positions if p.is_catastrophic]
    catastrophes.sort(key=lambda p: p.executable_peak_multiple, reverse=True)

    tokens = []
    for position in catastrophes[:limit]:
        peak = position.executable_peak_multiple
        collapse = (
            (position.closed_at - position.opened_at).total_seconds() / 60
            if position.closed_at
            else None
        )
        per_strategy = []
        for book in books:
            match = next(
                (p for p in book.result.positions if p.mint_address == position.mint_address),
                None,
            )
            if match is None:
                continue
            per_strategy.append(
                {
                    "strategy_id": book.wallet.strategy_id,
                    "invested": _d(match.size_usd),
                    "recovered_before": _d(match.banked_before_final),
                    "net_pnl": _d(match.net_pnl),
                    "return_pct": _d(match.return_pct),
                }
            )
        tokens.append(
            {
                "mint_address": position.mint_address,
                "opened_at": position.opened_at.isoformat(),
                "minutes_to_collapse": collapse,
                "executable_peak_multiple": _d(peak),
                "observed_peak_multiple": _d(position.observed_peak_multiple),
                "reached_125": peak >= Decimal("1.25"),
                "reached_150": peak >= Decimal("1.50"),
                "reached_175": peak >= Decimal("1.75"),
                "reached_200": peak >= Decimal(2),
                "strategies": per_strategy,
            }
        )

    return {
        "banner": BANNER,
        "definition": (
            "A catastrophe is a position whose pool became non-executable "
            "(DEAD_POOL or UNTRADABLE), or which lost 90% or more. Positions "
            "whose series simply ran out while the pool still looked healthy "
            "are counted as unsettled, NOT as rugs."
        ),
        "control_strategy": control.wallet.strategy_id,
        "tokens": tokens,
        "by_strategy": [
            {
                "strategy_id": b.row.strategy_id,
                "name": b.row.name,
                "rugs": b.row.rug_impact.count,
                "capital_invested": _d(b.row.rug_impact.capital_invested),
                "capital_recovered_before": _d(b.row.rug_impact.capital_recovered_before),
                "net_loss": _d(b.row.rug_impact.net_loss),
                "recovery_pct": (
                    _d(
                        b.row.rug_impact.capital_recovered_before
                        / b.row.rug_impact.capital_invested
                        * 100
                    )
                    if b.row.rug_impact.capital_invested > 0
                    else None
                ),
                "reached_125": b.row.rug_impact.reached_125,
                "reached_150": b.row.rug_impact.reached_150,
                "reached_175": b.row.rug_impact.reached_175,
                "reached_200": b.row.rug_impact.reached_200,
            }
            for b in sorted(books, key=lambda b: b.wallet.strategy_id)
        ],
        "dataset": _dataset(run),
    }


@router.get("/experiments")
async def experiments(
    session: DbSession,
    mode: Annotated[str, Query()] = LabState.BACKTEST.value,
) -> dict[str, Any]:
    """§16, §21 and §24 in one place: matrix, robustness, and day regimes."""
    mode = _mode_param(mode)
    books, run = await _books(session, mode=mode, since=None)
    control = next((b for b in books if b.wallet.strategy_id == "S5"), None)
    day_regimes = metrics.regimes(control.result) if control else []

    return {
        "banner": BANNER,
        "matrix": {
            "rows": [d.strategy_id for d in ALL],
            "columns": [
                "entry_25",
                "no_initial_stop",
                "partial_profits",
                "expiry_6h",
                "runner",
                "survival_gate",
                "time_decay",
                "trailing",
            ],
            "values": {d.strategy_id: d.matrix_row() for d in ALL},
        },
        "robustness": [
            {
                "strategy_id": b.row.strategy_id,
                "name": b.row.name,
                "n": b.row.n,
                "normal_pnl": _d(b.row.robustness.normal_pnl),
                "ex_best_1_pnl": _d(b.row.robustness.ex_best_1_pnl),
                "ex_best_3_pnl": _d(b.row.robustness.ex_best_3_pnl),
                "ex_worst_1_pnl": _d(b.row.robustness.ex_worst_1_pnl),
                "ex_worst_3_pnl": _d(b.row.robustness.ex_worst_3_pnl),
                "top_1_share_pct": _d(b.row.robustness.top_1_share_pct),
                "top_3_share_pct": _d(b.row.robustness.top_3_share_pct),
                "top_5_share_pct": _d(b.row.robustness.top_5_share_pct),
                "outlier_dependent": b.row.robustness.outlier_dependent,
                "flags": list(b.row.flags),
            }
            for b in sorted(books, key=lambda b: b.wallet.strategy_id)
        ],
        "regime": {
            "version": metrics.REGIME_VERSION,
            "definition": metrics.REGIME_DEFINITION,
            "days": [
                {
                    "day": r.day,
                    "opportunities": r.opportunities,
                    "catastrophe_rate_pct": _d(r.catastrophe_rate_pct),
                    "label": r.label,
                }
                for r in day_regimes
            ],
        },
        "sampling": {
            "in_sample": (
                "Every result on this page is IN-SAMPLE. The ten strategies were "
                "specified before the replay and no parameter was fitted to this "
                "data, but none of them has been validated out-of-sample or "
                "forward-tested. Winning a backtest is not validation."
            ),
            "anti_overfitting": (
                "No threshold was optimised. Discovery, validation and forward "
                "periods are separable by the `since`/`until` window on the "
                "canonical loader; nothing has been split yet because there is "
                "not yet enough data to spend on a holdout."
            ),
        },
        "dataset": _dataset(run),
    }


@router.get("/status")
async def status(session: DbSession) -> dict[str, Any]:
    """Operational state. What is running, and proof of what cannot run."""
    state = service.current_state()
    run = await reporting.latest_run(session)
    forward = await reporting.load_books(session, mode=LabState.FORWARD_RESEARCH.value)
    return {
        "banner": BANNER,
        "state": state.value,
        "states_available": [s.value for s in LabState],
        "live_execution_path": "NONE",
        "signer": "NONE",
        "forward_research_active": state is LabState.FORWARD_RESEARCH,
        "forward_wallets": len(forward),
        "forward_positions": sum(len(b.result.positions) for b in forward),
        "tick_seconds": settings.STRATEGY_LAB_TICK_SECONDS,
        "latest_backtest": _dataset(run),
    }
