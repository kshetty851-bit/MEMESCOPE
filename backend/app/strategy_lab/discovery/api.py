"""`/api/v1/strategy-lab/discovery` — search surfaces. **Read-only.**

No POST, no PUT, no PATCH, no DELETE. A search is started by an operator on the
host, never by an HTTP request: the run takes minutes and evaluates thousands of
definitions, and a page load that could trigger one would be a denial-of-service
button wearing a chart.

Every figure served here is simulated research over stored observations. Nothing
here recommends a trade, and a candidate reaching CHAMPION means it earned a
fresh $1,000 *simulated* forward wallet — never a promotion.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api.deps import DbSession
from app.models.strategy_lab_discovery import (
    StrategyLabDiscoveryCandidate,
    StrategyLabDiscoveryResult,
    StrategyLabDiscoveryRun,
)
from app.strategy_lab.discovery import repository, scoring, service, space

router = APIRouter(prefix="/strategy-lab/discovery", tags=["strategy-lab"])

BANNER = "Research Only — No Capital Execution"

DATASETS = (service.DATASET_LOCAL_BACKTEST, service.DATASET_PRODUCTION_FORWARD)

BLOCKS = ("DISCOVERY", "VALIDATION", "HOLDOUT", "WALK_FORWARD")


def _dataset(value: str) -> str:
    if value not in DATASETS:
        raise HTTPException(422, f"dataset must be one of {list(DATASETS)}")
    return value


def _f(value: Any) -> float | None:
    return None if value is None else float(value)


async def _run(session: DbSession, dataset: str) -> StrategyLabDiscoveryRun | None:
    return await repository.latest_run(session, dataset_source=dataset)


@router.get("/overview")
async def overview(
    session: DbSession,
    dataset: Annotated[str, Query()] = service.DATASET_LOCAL_BACKTEST,
) -> dict[str, Any]:
    """§27's Search Overview: the funnel, the split, and what limits it."""
    dataset = _dataset(dataset)
    run = await _run(session, dataset)
    if run is None:
        return {
            "banner": BANNER,
            "dataset_source": dataset,
            "has_run": False,
            "search_space": space.summary(),
        }
    return {
        "banner": BANNER,
        "dataset_source": dataset,
        "has_run": True,
        "run_id": str(run.id),
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "runtime_seconds": _f(run.runtime_seconds),
        "schedule_resolutions": run.schedule_resolutions,
        "engine_version": run.engine_version,
        "space_version": run.space_version,
        "scoring_version": run.scoring_version,
        "canonical_version": run.canonical_version,
        "universe_usable": run.universe_usable,
        "exclusions": run.exclusions,
        "split": run.split,
        "funnel": run.funnel,
        "search_space": run.search_space,
        "ranking": (
            "DISCOVERY_SCORE = penalise(robust return, by drawdown, sample, "
            "capture and day consistency). Penalties multiply a gain and DIVIDE "
            "a loss, so they always move a score down — a strategy is never "
            "rewarded for trading less."
        ),
        "evidence_floor_n": scoring.EVIDENCE_FLOOR_N,
        "preferred_n": scoring.MIN_OOS_TRADES,
        "min_capture_pct": float(scoring.MIN_CAPTURE_PCT),
    }


@router.get("/space")
async def search_space(
    session: DbSession,
    dataset: Annotated[str, Query()] = service.DATASET_LOCAL_BACKTEST,
) -> dict[str, Any]:
    """§27's Search Space: every dimension, every level, and every omission."""
    dataset = _dataset(dataset)
    run = await _run(session, dataset)
    return {
        "banner": BANNER,
        "dataset_source": dataset,
        "summary": run.search_space if run else space.summary(),
        "entries": [
            {"key": e.key, "label": e.label, "family": e.family, "rule": e.describe()}
            for e in space.ENTRIES
        ],
        "sizes": [str(s) for s in space.SIZES],
        "legacy_size": str(space.LEGACY_SIZE),
        "profits": [
            {"key": p.key, "label": p.label, "rule": p.describe()} for p in space.PROFITS
        ],
        "exits": [
            {"key": x.key, "label": x.label, "family": x.family, "rule": x.describe()}
            for x in space.EXITS
        ],
        "portfolios": [
            {"key": r.key, "label": r.label, "rule": r.describe()} for r in space.PORTFOLIOS
        ],
        "unavailable_features": space.UNAVAILABLE_FEATURES,
        "future_features_not_ready": space.FUTURE_FEATURES_NOT_READY,
        "notes": [space.EXIT_FAMILIES_NOTE, space.P3_P6_EQUIVALENCE],
    }


@router.get("/candidates")
async def candidates(
    session: DbSession,
    dataset: Annotated[str, Query()] = service.DATASET_LOCAL_BACKTEST,
    block: Annotated[str, Query()] = "DISCOVERY",
    status: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, Any]:
    """§28's candidate table, for one block."""
    dataset = _dataset(dataset)
    if block not in BLOCKS:
        raise HTTPException(422, f"block must be one of {list(BLOCKS)}")
    run = await _run(session, dataset)
    if run is None:
        return {"banner": BANNER, "dataset_source": dataset, "has_run": False, "rows": []}

    query = (
        select(StrategyLabDiscoveryCandidate, StrategyLabDiscoveryResult)
        .join(
            StrategyLabDiscoveryResult,
            StrategyLabDiscoveryResult.candidate_id == StrategyLabDiscoveryCandidate.id,
        )
        .where(
            StrategyLabDiscoveryCandidate.run_id == run.id,
            StrategyLabDiscoveryResult.block == block,
        )
        .order_by(StrategyLabDiscoveryResult.score.desc().nullslast())
        .limit(limit)
    )
    if status:
        query = query.where(StrategyLabDiscoveryCandidate.status == status)

    rows = (await session.execute(query)).all()
    return {
        "banner": BANNER,
        "dataset_source": dataset,
        "has_run": True,
        "block": block,
        "run_id": str(run.id),
        "rows": [
            _row(candidate, result, rank) for rank, (candidate, result) in enumerate(rows, 1)
        ],
    }


def _row(
    candidate: StrategyLabDiscoveryCandidate, result: StrategyLabDiscoveryResult, rank: int
) -> dict[str, Any]:
    metrics = result.metrics or {}
    robustness = metrics.get("robustness", {})
    moonshots = metrics.get("moonshots", [])

    def retention(level: str) -> float | None:
        for m in moonshots:
            if str(m.get("level")) == level:
                value = m.get("retention_pct")
                return None if value is None else float(value)
        return None

    return {
        "rank": rank,
        "strategy_id": candidate.strategy_id,
        "version": candidate.version,
        "definition_hash": candidate.definition_hash,
        "explanation": candidate.explanation,
        "factors": candidate.factors,
        "entry_rules": candidate.factors.get("entry"),
        "size": candidate.factors.get("size"),
        "profit": candidate.factors.get("profit"),
        "exit": candidate.factors.get("exit"),
        "portfolio": candidate.factors.get("portfolio"),
        "reference": candidate.reference,
        "status": candidate.status,
        "n": result.n,
        "offered": result.offered,
        "capture_pct": _f(result.capture_pct),
        "final_equity": _f(result.final_equity),
        "return_pct": _f(result.return_pct),
        "profit_factor": _f(result.profit_factor),
        "expectancy": _f(result.expectancy),
        "max_drawdown_pct": _f(result.max_drawdown_pct),
        "win_rate_pct": _f(result.win_rate_pct),
        "rug_loss_usd": _f(result.rug_loss_usd),
        "score": _f(result.score),
        "survives": result.survives,
        "flags": result.flags,
        "retention_2x": retention("2"),
        "retention_5x": retention("5"),
        "profitable_day_pct": _f((metrics.get("daily") or {}).get("profitable_day_pct")),
        "outlier_dependent": bool(robustness.get("outlier_dependent")),
        "outlier_dependent_top3": bool(robustness.get("outlier_dependent_top3")),
    }


@router.get("/candidates/{strategy_id}")
async def candidate_detail(
    session: DbSession,
    strategy_id: str,
    dataset: Annotated[str, Query()] = service.DATASET_LOCAL_BACKTEST,
) -> dict[str, Any]:
    """One candidate across every block it reached, with its full metrics."""
    dataset = _dataset(dataset)
    run = await _run(session, dataset)
    if run is None:
        raise HTTPException(404, "no search has been recorded")

    candidate = (
        await session.execute(
            select(StrategyLabDiscoveryCandidate).where(
                StrategyLabDiscoveryCandidate.run_id == run.id,
                StrategyLabDiscoveryCandidate.strategy_id == strategy_id,
            )
        )
    ).scalar_one_or_none()
    if candidate is None:
        raise HTTPException(404, f"unknown candidate {strategy_id!r}")

    results = (
        (
            await session.execute(
                select(StrategyLabDiscoveryResult).where(
                    StrategyLabDiscoveryResult.candidate_id == candidate.id
                )
            )
        )
        .scalars()
        .all()
    )

    return {
        "banner": BANNER,
        "dataset_source": dataset,
        "strategy_id": candidate.strategy_id,
        "version": candidate.version,
        "definition_hash": candidate.definition_hash,
        "definition": candidate.definition,
        "explanation": candidate.explanation,
        "factors": candidate.factors,
        "status": candidate.status,
        "reference": candidate.reference,
        "blocks": {
            r.block: {
                "n": r.n,
                "offered": r.offered,
                "capture_pct": _f(r.capture_pct),
                "final_equity": _f(r.final_equity),
                "return_pct": _f(r.return_pct),
                "profit_factor": _f(r.profit_factor),
                "expectancy": _f(r.expectancy),
                "max_drawdown_pct": _f(r.max_drawdown_pct),
                "win_rate_pct": _f(r.win_rate_pct),
                "rug_loss_usd": _f(r.rug_loss_usd),
                "score": _f(r.score),
                "survives": r.survives,
                "flags": r.flags,
                "metrics": r.metrics,
            }
            for r in results
        },
    }


@router.get("/champions")
async def champions(
    session: DbSession,
    dataset: Annotated[str, Query()] = service.DATASET_LOCAL_BACKTEST,
) -> dict[str, Any]:
    """§25. Up to five, or an explicit none — which is an acceptable result."""
    dataset = _dataset(dataset)
    run = await _run(session, dataset)
    if run is None:
        return {"banner": BANNER, "dataset_source": dataset, "has_run": False, "champions": []}

    rows = (
        (
            await session.execute(
                select(StrategyLabDiscoveryCandidate).where(
                    StrategyLabDiscoveryCandidate.run_id == run.id,
                    StrategyLabDiscoveryCandidate.status == scoring.Status.CHAMPION,
                )
            )
        )
        .scalars()
        .all()
    )

    return {
        "banner": BANNER,
        "dataset_source": dataset,
        "has_run": True,
        "verdict": _verdict(run, len(rows)),
        "next_step": (
            "A champion earns a fresh $1,000 SIMULATED forward-research wallet when "
            "Strategy Lab is production-enabled. It is never promoted to Paper "
            "Wallet V1 or V2, and it never reaches real capital."
        ),
        "standards": [
            "OOS PF >= 1.20",
            "positive expectancy",
            "positive wallet return",
            "max DD <= 40%",
            "capture >= 20%",
            f"N >= {scoring.MIN_OOS_TRADES}",
            "profitable without its best trade",
            "profitable across multiple days",
        ],
        "champions": [
            {
                "strategy_id": c.strategy_id,
                "explanation": c.explanation,
                "definition_hash": c.definition_hash,
                "factors": c.factors,
            }
            for c in rows
        ],
    }


def _verdict(run: StrategyLabDiscoveryRun, champion_count: int) -> str:
    if champion_count:
        return "C. FORWARD CHAMPIONS FOUND"
    funnel = run.funnel or {}
    if funnel.get("holdout_survivors") or funnel.get("validation_survivors"):
        return "A. NO STRATEGY FOUND"
    warnings = ((run.split or {}).get("diagnosis") or {}).get("warnings") or []
    return "B. MORE DATA REQUIRED" if warnings else "A. NO STRATEGY FOUND"


@router.get("/attribution")
async def attribution(
    session: DbSession,
    dataset: Annotated[str, Query()] = service.DATASET_LOCAL_BACKTEST,
) -> dict[str, Any]:
    """§30. Which design choices associate with better results — in this data."""
    dataset = _dataset(dataset)
    run = await _run(session, dataset)
    if run is None:
        return {
            "banner": BANNER,
            "dataset_source": dataset,
            "has_run": False,
            "dimensions": {},
        }
    return {
        "banner": BANNER,
        "dataset_source": dataset,
        "has_run": True,
        "caveat": (
            "Association, not causation. The search is a full factorial, so these "
            "marginal means are fair comparisons WITHIN this dataset — which is "
            "one market over one short window."
        ),
        "dimensions": run.attribution,
    }
