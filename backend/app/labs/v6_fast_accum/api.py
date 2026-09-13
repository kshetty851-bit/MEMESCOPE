"""`/labs/v6-fast-accum` — read-only. `RESEARCH_ONLY`.

No POST, PUT, PATCH or DELETE. A research result is a thing that was computed
once from a frozen dataset; an endpoint that let the browser re-run it with
different thresholds would be a second, unpublished experiment competing with
the pre-registered one, and the two would disagree the first time either moved.

Re-running is a deliberate operator action — `python -m app.labs.v6_fast_accum`
— not an HTTP request.

Every figure arrives already computed. The dashboard renders; it does not
decide.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.labs.v6_fast_accum import config
from app.labs.v6_fast_accum.models import V6LabRun, V6LabTrade

router = APIRouter(prefix="/labs/v6-fast-accum", tags=["v6-fast-accum-lab"])


@router.get("/latest")
async def latest(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """The most recent run, whole.

    `has_run: false` rather than an empty result when nothing has run yet:
    "the lab has not run" and "the lab ran and found nothing" are different
    facts and must not render identically.
    """
    row = (await db.execute(
        select(V6LabRun).order_by(desc(V6LabRun.started_at)).limit(1)
    )).scalar_one_or_none()
    if row is None:
        return {"has_run": False, "research_only": True,
                "spec_version": config.SPEC_VERSION,
                "config_hash": config.config_hash()}
    return {
        "has_run": True,
        "research_only": True,
        "experiment_id": row.experiment_id,
        "spec_version": row.spec_version,
        "config_hash": row.config_hash,
        "dataset_version": row.dataset_version,
        "git_sha": row.git_sha,
        "random_seed": row.random_seed,
        "started_at": row.started_at.isoformat(),
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "verdict": row.verdict,
        "gate_passed": row.gate_passed,
        "leakage_passed": row.leakage_passed,
        "result": row.result,
    }


@router.get("/runs")
async def runs(limit: int = 20, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Every run, newest first — the reproducibility trail.

    Two rows sharing `config_hash` and `dataset_version` tested the same
    hypothesis on the same data and must carry the same verdict. A pair that
    does not is a bug, and this list is where it becomes visible.
    """
    rows = (await db.execute(
        select(V6LabRun).order_by(desc(V6LabRun.started_at)).limit(min(limit, 100))
    )).scalars().all()
    return {"research_only": True, "runs": [
        {"experiment_id": r.experiment_id, "started_at": r.started_at.isoformat(),
         "config_hash": r.config_hash, "dataset_version": r.dataset_version,
         "git_sha": r.git_sha, "verdict": r.verdict, "gate_passed": r.gate_passed}
        for r in rows]}


@router.get("/trades")
async def trades(strategy: str | None = None, limit: int = 200,
                 db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Per-trade rows of the latest run, censored ones included and flagged.

    Censored rows are returned rather than filtered out. They are the trades the
    collector stopped watching, and a reader who cannot see them cannot judge
    how much of the book the archive actually resolved.
    """
    run = (await db.execute(
        select(V6LabRun).order_by(desc(V6LabRun.started_at)).limit(1)
    )).scalar_one_or_none()
    if run is None:
        return {"has_run": False, "trades": []}
    q = select(V6LabTrade).where(V6LabTrade.run_id == run.id)
    if strategy:
        q = q.where(V6LabTrade.strategy == strategy)
    rows = (await db.execute(
        q.order_by(desc(V6LabTrade.entry_ts)).limit(min(limit, 1000))
    )).scalars().all()
    return {
        "has_run": True, "research_only": True, "experiment_id": run.experiment_id,
        "trades": [
            {"mint": t.mint, "strategy": t.strategy,
             "entry_ts": t.entry_ts.isoformat(),
             "exit_ts": t.exit_ts.isoformat() if t.exit_ts else None,
             "exit_reason": t.exit_reason, "censored": t.censored,
             "entry_progress_pct": float(t.entry_progress_pct) if t.entry_progress_pct is not None else None,
             "entry_mcap_sol": float(t.entry_mcap_sol) if t.entry_mcap_sol is not None else None,
             "elapsed_s": float(t.elapsed_s) if t.elapsed_s is not None else None,
             "net_return": float(t.net_return) if t.net_return is not None else None,
             "net_pnl_usd": float(t.net_pnl_usd) if t.net_pnl_usd is not None else None,
             "mfe": float(t.mfe) if t.mfe is not None else None,
             "mae": float(t.mae) if t.mae is not None else None,
             "reached_100": t.reached_100, "graduated": t.graduated}
            for t in rows]}
