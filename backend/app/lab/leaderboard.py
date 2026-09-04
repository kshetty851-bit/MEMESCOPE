"""Leaderboard, the three leader badges, robustness columns, and snapshots.

Every number here is computed from the ledger, never carried in a cache. Equity
is cash plus EXECUTABLE open value; deployed cost is shown beside it but never
counted as value (mission §6, §22).

The three badges are deliberately independent — a strategy that leads on profit
and destroys its wallet doing it must not also be presented as risk-adjusted or
2x leader (mission §20).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.lab import spec
from app.models.lab import LabPosition, LabStrategy, LabTournament

#: Sample-size language, from the Arena protocol. A leader with fewer closed
#: trades than this is reported as observed profit, never as evidence of edge.
CONFIDENCE_STEPS = ((500, "SUBSTANTIAL"), (200, "INTERMEDIATE"), (100, "PRELIMINARY"),
                    (50, "EARLY"), (25, "EXTREMELY_LOW_CONFIDENCE"))
MIN_TRADES_FOR_RISK_BADGE = 5

#: The non-trading control, exempted from the minimum-trades gate because doing
#: nothing IS its result and it can never accumulate trades to qualify.
#:
#: Derived from the spec rather than hardcoded. It read "V6-01" until the V7
#: registry renumbered everything, at which point the cash control would have
#: silently dropped off the risk board — the one row whose whole purpose is to
#: be compared against.
_CASH_CONTROLS: frozenset[str] = frozenset(
    s.id for s in spec.STRATEGIES if not s.trades
)


def confidence(closed: int) -> str:
    for floor, label in CONFIDENCE_STEPS:
        if closed >= floor:
            return label
    return "INSUFFICIENT_SAMPLE"


def _pnl(p: LabPosition) -> Decimal:
    return (p.exit_proceeds_usd or Decimal(0)) - p.size_usd


async def strategy_rows(session: AsyncSession, *, tournament_id: uuid.UUID,
                        before: datetime | None = None
                        ) -> list[dict[str, Any]]:
    """One row per strategy IN ONE TOURNAMENT. `before` bounds the book to a
    snapshot boundary.

    `tournament_id` is required rather than defaulted. This query had no
    tournament filter at all, which was invisible while exactly one record
    existed and wrong the instant a second did: V6.1 opened at $100 and the board
    rendered V6's $1,000 rows underneath a 1.1.0 header. A default would have
    reintroduced the same silence.
    """
    strategies = list((await session.execute(
        select(LabStrategy)
        .where(LabStrategy.tournament_id == tournament_id)
        .order_by(LabStrategy.strategy_id)
    )).scalars())
    out = []
    for row in strategies:
        q = select(LabPosition).where(LabPosition.strategy_row_id == row.id)
        if before is not None:
            q = q.where(LabPosition.opened_at <= before)
        positions = list((await session.execute(q)).scalars())
        # At a snapshot boundary a position closed AFTER it was still open then.
        closed = [p for p in positions if p.status == "closed"
                  and (before is None or (p.closed_at and p.closed_at <= before))]
        opens = [p for p in positions if p not in closed]

        pnls = sorted((_pnl(p) for p in closed), reverse=True)
        wins = [x for x in pnls if x > 0]
        losses = [x for x in pnls if x <= 0]
        gross_win = sum(wins) or Decimal(0)
        gross_loss = -sum(losses) or Decimal(0)

        open_cost = sum((p.size_usd for p in opens), Decimal(0))
        open_value = sum(
            ((p.snapshot_value_usd if (before is not None and p.snapshot_value_usd is not None)
              else (p.last_open_value_usd if p.last_open_value_usd is not None else p.size_usd))
             for p in opens), Decimal(0)
        )
        realized = sum(pnls, Decimal(0))
        # Return on the money that is actually AT RISK, not on the wallet.
        # With $10 positions against $1,000 a strategy is ~99% idle cash, so
        # `return_pct` compresses every candidate into the same tenth of a
        # percent and hides which of them can trade. These two undo that:
        #   open_return_pct     — how the book it holds RIGHT NOW is doing
        #   deployed_return_pct — how every dollar it has ever committed did
        deployed_ever = sum((p.size_usd for p in positions), Decimal(0))
        open_pnl = open_value - open_cost
        total_pnl = realized + open_pnl
        # Cash is reconstructed rather than read, so a snapshot bounded in the
        # past is consistent with the positions it actually contains.
        cash = row.starting_equity - open_cost + realized
        equity = cash + open_value

        marked = [p for p in positions if p.reached_125 or p.status == "closed"]
        n_marked = len(marked) or 1
        out.append({
            "strategy_id": row.strategy_id, "name": row.name, "status": row.status,
            "failed_reason": row.failed_reason,
            "checkpoint_minutes": row.checkpoint_minutes,
            "size_usd": row.size_usd, "max_concurrent": row.max_concurrent,
            "max_exposure_usd": row.max_exposure_usd,
            "starting_equity": row.starting_equity,
            "cash": cash, "open_cost": open_cost, "open_value": open_value,
            "equity": equity,
            "net_pnl": equity - row.starting_equity,
            "return_pct": ((equity / row.starting_equity - 1) * 100
                           if row.starting_equity else Decimal(0)),
            "open_cost_basis": open_cost,
            "open_pnl": open_pnl,
            "open_return_pct": ((open_pnl / open_cost * 100) if open_cost > 0 else None),
            "deployed_ever": deployed_ever,
            "deployed_return_pct": ((total_pnl / deployed_ever * 100)
                                    if deployed_ever > 0 else None),
            "capital_at_work_pct": ((open_cost / row.starting_equity * 100)
                                    if row.starting_equity else Decimal(0)),
            "trades": len(closed), "open_positions": len(opens),
            "wins": len(wins), "losses": len(losses),
            "win_pct": (Decimal(len(wins)) / len(closed) * 100) if closed else None,
            "expectancy": (realized / len(closed)) if closed else None,
            "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else None,
            "max_dd_pct": ((row.peak_equity - equity) / row.peak_equity * 100
                           if row.peak_equity and equity < row.peak_equity else Decimal(0)),
            "avg_position": (open_cost / len(opens)) if opens else row.size_usd,
            "exec_125_pct": Decimal(sum(1 for p in marked if p.reached_125)) / n_marked * 100,
            "exec_150_pct": Decimal(sum(1 for p in marked if p.reached_150)) / n_marked * 100,
            "exec_200_pct": Decimal(sum(1 for p in marked if p.reached_200)) / n_marked * 100,
            "best_trade": pnls[0] if pnls else None,
            "worst_trade": pnls[-1] if pnls else None,
            "expectancy_ex_best1": (sum(pnls[1:], Decimal(0)) / (len(pnls) - 1)
                                    if len(pnls) > 1 else None),
            "expectancy_ex_best3": (sum(pnls[3:], Decimal(0)) / (len(pnls) - 3)
                                    if len(pnls) > 3 else None),
            "top1_profit_share_pct": ((pnls[0] / gross_win * 100)
                                      if gross_win > 0 and pnls and pnls[0] > 0 else None),
            "top3_profit_share_pct": ((sum(x for x in pnls[:3] if x > 0) / gross_win * 100)
                                      if gross_win > 0 else None),
            "losing_streak": _longest_losing_streak(closed),
            "confidence": confidence(len(closed)),
            "evidence": spec.BY_ID[row.strategy_id].evidence,
            "overfit_risk": spec.BY_ID[row.strategy_id].overfit_risk,
            "hist": spec.BY_ID[row.strategy_id].hist,
            "hist_is_proxy": spec.BY_ID[row.strategy_id].hist_is_proxy,
        })
    return out


def _longest_losing_streak(closed: list[LabPosition]) -> int:
    run = best = 0
    for p in sorted(closed, key=lambda x: x.closed_at or x.opened_at):
        if _pnl(p) <= 0:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def leaders(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The three badges. Independent by construction; ties break on more trades."""
    if not rows:
        return {}
    profit = max(rows, key=lambda r: (r["equity"], r["trades"]))

    def risk_score(r: dict[str, Any]) -> tuple:
        # Only strategies with enough closed trades to have a shape compete;
        # a wallet that has done nothing is not "risk-adjusted excellent".
        if r["trades"] < MIN_TRADES_FOR_RISK_BADGE and r["strategy_id"] not in _CASH_CONTROLS:
            return (-1, Decimal(0))
        pf = r["profit_factor"] or Decimal(0)
        dd = r["max_dd_pct"] or Decimal(0)
        conc = r["top3_profit_share_pct"]
        # Return per unit of drawdown, discounted when the profit came from a
        # handful of trades — the failure mode V6's red team kept finding.
        base = r["return_pct"] / (1 + dd)
        if conc is not None and conc > 80:
            base = base * Decimal("0.5")
        return (1, base + pf)

    risk = max(rows, key=risk_score)
    two_x = max(rows, key=lambda r: (r["exec_200_pct"], r["trades"]))
    return {
        "profit": {"strategy_id": profit["strategy_id"], "name": profit["name"],
                   "equity": profit["equity"], "return_pct": profit["return_pct"],
                   "confidence": profit["confidence"]},
        "risk_adjusted": {"strategy_id": risk["strategy_id"], "name": risk["name"],
                          "return_pct": risk["return_pct"],
                          "profit_factor": risk["profit_factor"],
                          "max_dd_pct": risk["max_dd_pct"], "trades": risk["trades"],
                          "confidence": risk["confidence"]},
        "executable_2x": {"strategy_id": two_x["strategy_id"], "name": two_x["name"],
                          "exec_200_pct": two_x["exec_200_pct"],
                          "trades": two_x["trades"], "confidence": two_x["confidence"]},
    }


async def mark_open_at_boundary(session: AsyncSession, *, tournament_id: uuid.UUID,
                                boundary: datetime) -> int:
    """Stamp each open position's executable value at the boundary, once.

    Positions are NOT force-closed: that rule was frozen before launch
    (mission §24). They are marked for the snapshot and then continue normally
    in the ongoing tournament.
    """
    opens = list((await session.execute(
        select(LabPosition)
        .join(LabStrategy, LabStrategy.id == LabPosition.strategy_row_id)
        .where(LabStrategy.tournament_id == tournament_id,
               LabPosition.status == "open",
               LabPosition.opened_at <= boundary,
               LabPosition.snapshot_value_usd.is_(None))
    )).scalars())
    for pos in opens:
        pos.snapshot_value_usd = (pos.last_open_value_usd
                                  if pos.last_open_value_usd is not None else pos.size_usd)
    await session.flush()
    return len(opens)


async def build_snapshot(session: AsyncSession, *, tournament: LabTournament,
                         label: str, boundary: datetime, now: datetime) -> dict[str, Any]:
    await mark_open_at_boundary(session, tournament_id=tournament.id,
                                boundary=boundary)
    rows = await strategy_rows(session, tournament_id=tournament.id, before=boundary)
    rows.sort(key=lambda r: r["equity"], reverse=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    total_closed = sum(r["trades"] for r in rows)
    return {
        "label": label,
        "boundary_at": boundary.isoformat(),
        "taken_at": now.isoformat(),
        "spec_version": tournament.spec_version,
        "spec_hash": tournament.spec_hash,
        "valid_from": tournament.valid_from.isoformat(),
        "elapsed_hours": (boundary - tournament.valid_from).total_seconds() / 3600,
        "total_closed_trades": total_closed,
        "overall_confidence": confidence(total_closed),
        "leaders": _jsonable(leaders(rows)),
        "strategies": [_jsonable(r) for r in rows],
    }


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonable(v) for v in obj]
    return obj
