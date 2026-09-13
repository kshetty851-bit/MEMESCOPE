"""`/labs/forex-lab` — read-only. Backtest only.

No POST, PUT, PATCH or DELETE, and no query parameter that changes an
assumption. A backtest result is a thing computed once from a frozen dataset by
an operator command — `python -m app.labs.forex_lab sweep` then `publish` —
and an endpoint that let a browser re-run it with a different step size, a
different spread or a different gate would be a second, unpublished experiment
competing with the pre-registered one. The gate in particular was written down
before the sweep ran; a gate the reader can move is not a gate.

Nothing here places an order. The lab holds no wallet, live or paper: every
figure it reports is a replay over stored candles.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.labs.forex_lab import config
from app.labs.forex_lab.models import FxCandle, FxSweepRun

router = APIRouter(prefix="/labs/forex-lab", tags=["forex-lab"])


def _run_payload(row: FxSweepRun) -> dict[str, Any]:
    return {
        "has_run": True,
        "backtest_only": True,
        "run_id": str(row.id),
        "created_at": row.created_at.isoformat(),
        "symbol": row.symbol,
        "first_minute": row.first_minute.isoformat(),
        "last_minute": row.last_minute.isoformat(),
        "candles": row.candles,
        "git_sha": row.git_sha,
        "best_config": row.best_config,
        "gate_passed": row.gate_passed,
        "result": row.result,
    }


@router.get("/latest")
async def latest(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """The most recent sweep, whole.

    `has_run: false` rather than an empty result when nothing has been
    published: "the sweep has not run" and "the sweep ran and the grid lost
    money" are different facts and must not render identically.
    """
    row = (await db.execute(
        select(FxSweepRun).order_by(desc(FxSweepRun.created_at)).limit(1)
    )).scalar_one_or_none()
    if row is None:
        return {
            "has_run": False,
            "backtest_only": True,
            "symbol": config.SYMBOL,
            "window": {"start": config.START.isoformat(),
                       "end": config.END.isoformat()},
            "gate": _GATE_SUMMARY,
        }
    payload = _run_payload(row)
    payload["gate"] = _GATE_SUMMARY
    return payload


@router.get("/runs")
async def runs(limit: int = 20, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Every published sweep, newest first.

    Two sweeps over the same window with the same configuration must reach the
    same verdict — the engine is deterministic and a test asserts it. A pair
    here that does not is a bug, and this list is where it becomes visible.
    """
    rows = (await db.execute(
        select(FxSweepRun).order_by(desc(FxSweepRun.created_at)).limit(min(limit, 100))
    )).scalars().all()
    return {"backtest_only": True, "runs": [
        {"run_id": str(r.id), "created_at": r.created_at.isoformat(),
         "first_minute": r.first_minute.isoformat(),
         "last_minute": r.last_minute.isoformat(), "candles": r.candles,
         "best_config": r.best_config, "gate_passed": r.gate_passed,
         "git_sha": r.git_sha}
        for r in rows]}


@router.get("/data")
async def data(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """What is loaded, so the page can say whether the replay covered the
    window the brief asked for rather than implying it did."""
    total, first, last = (await db.execute(
        select(func.count(), func.min(FxCandle.minute), func.max(FxCandle.minute))
        .where(FxCandle.symbol == config.SYMBOL)
    )).one()
    return {
        "symbol": config.SYMBOL,
        "candles": int(total or 0),
        "first_minute": first.isoformat() if first else None,
        "last_minute": last.isoformat() if last else None,
        "window": {"start": config.START.isoformat(), "end": config.END.isoformat()},
    }


#: Stated in PLAN.md before a single candle was replayed, and served alongside
#: every result so the page never has to restate it from memory.
_GATE_SUMMARY = {
    "profit_factor_min": 1.3,
    "years_positive_min": 4,
    "years_positive_of": 6,
    "must_include_year": 2022,
    "max_drawdown_pct_max": 25.0,
    "best_month_share_max": 0.30,
    "full_years": list(config.FULL_YEARS),
    "partial_year": config.PARTIAL_YEAR,
}
