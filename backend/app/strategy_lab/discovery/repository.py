"""Persisting a search. **Writes three tables, all inside the namespace.**

A run is written once, whole, at the end. There is no incremental write and no
update path: a search is an immutable record of what a fixed search space did
against a fixed dataset, and a row that could be revised afterwards would make
the holdout meaningless — §24's seal is only worth anything if the result it
produced cannot later be edited into a better one.

Superseding is by replacement, like `strategy_lab.service.run_backtest`: a newer
run over an overlapping universe is not additive to an older one, and keeping
both invites someone to average them.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.strategy_lab_discovery import (
    StrategyLabDiscoveryCandidate,
    StrategyLabDiscoveryResult,
    StrategyLabDiscoveryRun,
)
from app.strategy_lab.discovery import scoring, space
from app.strategy_lab.discovery.engine import Evaluation
from app.strategy_lab.discovery.service import SearchResult
from app.strategy_lab.opportunities import CANONICAL_VERSION

_ZERO = Decimal(0)


def _d(value: Any) -> Any:
    """JSON-safe: Decimals become strings, so nothing is silently rounded."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _d(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_d(v) for v in value]
    return value


def metrics_blob(evaluation: Evaluation, verdict: scoring.Verdict) -> dict[str, Any]:
    """Everything §14-§20 asks for, in one JSONB document."""
    return _d(
        {
            "robustness": {
                "normal_pnl": sum((t.net_pnl for t in evaluation.trades), _ZERO),
                "ex_best_1": evaluation.without(best=1),
                "ex_best_3": evaluation.without(best=3),
                "ex_best_5": evaluation.without(best=5),
                "ex_worst_1": evaluation.without(worst=1),
                "ex_worst_3": evaluation.without(worst=3),
                "top_1_share_pct": evaluation.top_share_pct(1),
                "top_3_share_pct": evaluation.top_share_pct(3),
                "top_5_share_pct": evaluation.top_share_pct(5),
                "outlier_dependent": evaluation.outlier_dependent,
                "outlier_dependent_top3": evaluation.outlier_dependent_top3,
            },
            "daily": {
                "by_day": evaluation.daily(),
                "profitable_day_pct": evaluation.profitable_day_pct,
                "best_day": evaluation.best_day,
                "worst_day": evaluation.worst_day,
                "stdev": evaluation.daily_return_stdev,
                "day_concentration_pct": evaluation.day_concentration_pct,
            },
            "moonshots": [
                evaluation.moonshot(level)
                for level in __import__(
                    "app.strategy_lab.discovery.engine", fromlist=["MOONSHOT_LEVELS"]
                ).MOONSHOT_LEVELS
            ],
            "rugs": {
                "count": len(evaluation.catastrophes),
                "loss_usd": evaluation.rug_loss_usd,
                "recovered_before": evaluation.rug_capital_recovered,
                "reached_125": evaluation.rugs_reaching("1.25"),
                "reached_150": evaluation.rugs_reaching("1.50"),
                "reached_175": evaluation.rugs_reaching("1.75"),
                "reached_200": evaluation.rugs_reaching("2.00"),
            },
            "refusals": evaluation.refusals,
            "peak_concurrent": evaluation.peak_concurrent,
            "score_components": verdict.components,
            "rejection_reasons": list(verdict.reasons),
            "champion_standards": [
                {"label": s.label, "met": s.met, "detail": s.detail}
                for s in scoring.champion_standards(evaluation)
            ],
        }
    )


async def persist(
    session: AsyncSession, result: SearchResult, *, supersede: bool = True
) -> uuid.UUID:
    """Write one whole search. Returns the run id."""
    previous = (
        (
            await session.execute(
                select(StrategyLabDiscoveryRun.id)
                .where(StrategyLabDiscoveryRun.dataset_source == result.dataset_source)
                .order_by(StrategyLabDiscoveryRun.started_at.desc())
            )
        )
        .scalars()
        .all()
    )

    run = StrategyLabDiscoveryRun(
        dataset_source=result.dataset_source,
        engine_version=result.engine_version,
        space_version=result.space_version,
        scoring_version=result.scoring_version,
        canonical_version=CANONICAL_VERSION,
        started_at=result.started_at,
        finished_at=result.finished_at,
        runtime_seconds=Decimal(str(round(result.seconds, 3))),
        schedule_resolutions=result.resolutions,
        universe_usable=result.usable,
        exclusions=result.excluded,
        split=_d(
            {
                **result.split.bounds(),
                "sizes": result.split.sizes(),
                "diagnosis": {
                    "calendar_days": result.split.diagnosis.calendar_days,
                    "substantial_days": result.split.diagnosis.substantial_days,
                    "largest_day_share_pct": result.split.diagnosis.largest_day_share_pct,
                    "granularity": result.split.diagnosis.granularity,
                    "warnings": list(result.split.diagnosis.warnings),
                },
                "walk_forward_folds": len(result.folds),
            }
        ),
        funnel=result.funnel(),
        search_space=_d(space.summary()),
        attribution=_d(
            {
                dimension: [
                    {
                        "level": level.level,
                        "n_strategies": level.n_strategies,
                        "mean_return_pct": level.mean_return_pct,
                        "median_return_pct": level.median_return_pct,
                        "mean_profit_factor": level.mean_profit_factor,
                        "mean_capture_pct": level.mean_capture_pct,
                        "survivors": level.survivors,
                        "survival_pct": level.survival_pct,
                    }
                    for level in levels
                ]
                for dimension, levels in result.attribution.items()
            }
        ),
    )
    session.add(run)
    await session.flush()

    statuses = _statuses(result)
    candidate_rows = []
    for candidate in result.candidates:
        candidate_rows.append(
            {
                "id": uuid.uuid4(),
                "run_id": run.id,
                "strategy_id": candidate.strategy_id,
                "version": candidate.version,
                "definition_hash": candidate.definition_hash,
                "definition": _d(candidate.canonical()),
                "explanation": candidate.explain(),
                "factors": candidate.factors(),
                "entry_size_usd": candidate.size_usd,
                "status": statuses[candidate.strategy_id],
                "reference": candidate.reference,
            }
        )
    if candidate_rows:
        await session.execute(insert(StrategyLabDiscoveryCandidate), candidate_rows)

    ids = {row["strategy_id"]: row["id"] for row in candidate_rows}
    blocks: list[tuple[str, dict[str, Evaluation], dict[str, scoring.Verdict]]] = [
        ("DISCOVERY", result.discovery.evaluations, result.discovery.verdicts),
        ("VALIDATION", result.validation.evaluations, result.validation.verdicts),
        ("HOLDOUT", result.holdout.evaluations, result.holdout.verdicts),
        (
            "WALK_FORWARD",
            result.walk_forward,
            {sid: scoring.judge(e) for sid, e in result.walk_forward.items()},
        ),
    ]

    result_rows = []
    for block, evaluations, verdicts in blocks:
        for strategy_id, evaluation in evaluations.items():
            candidate_id = ids.get(strategy_id)
            if candidate_id is None:
                continue
            verdict = verdicts[strategy_id]
            result_rows.append(
                {
                    "candidate_id": candidate_id,
                    "block": block,
                    "n": evaluation.n,
                    "offered": evaluation.offered,
                    "capture_pct": evaluation.capture_pct,
                    "final_equity": evaluation.final_cash,
                    "return_pct": evaluation.return_pct,
                    "profit_factor": _cap(evaluation.profit_factor),
                    "expectancy": evaluation.expectancy,
                    "max_drawdown_pct": evaluation.max_drawdown_pct,
                    "win_rate_pct": evaluation.win_rate_pct,
                    "rug_loss_usd": evaluation.rug_loss_usd,
                    "score": _cap(verdict.score),
                    "survives": verdict.survives,
                    "flags": list(verdict.flags),
                    "metrics": metrics_blob(evaluation, verdict),
                }
            )
    if result_rows:
        await session.execute(insert(StrategyLabDiscoveryResult), result_rows)

    if supersede and previous:
        await session.execute(
            delete(StrategyLabDiscoveryRun).where(
                StrategyLabDiscoveryRun.id.in_(list(previous))
            )
        )
    await session.commit()
    return run.id


def _cap(value: Decimal | None) -> Decimal | None:
    """Clamp into NUMERIC(14,4) so one absurd ratio cannot abort a whole run.

    Clamped rather than dropped: that a strategy produced an extreme figure is
    itself evidence, and losing the row would lose it.
    """
    if value is None:
        return None
    limit = Decimal("9999999999")
    return max(-limit, min(limit, value))


def _statuses(result: SearchResult) -> dict[str, str]:
    """The furthest stage each candidate reached. §28's Status column."""
    out: dict[str, str] = {}
    champions = set(result.champions)
    holdout_survivors = result.holdout.survivors()
    for candidate in result.candidates:
        sid = candidate.strategy_id
        if sid in champions:
            out[sid] = scoring.Status.CHAMPION
        elif sid in holdout_survivors:
            out[sid] = scoring.Status.HOLDOUT
        elif sid in result.validation.kept:
            out[sid] = scoring.Status.VALIDATION
        elif sid in result.discovery.kept:
            out[sid] = scoring.Status.DISCOVERY
        elif sid in result.discovery.evaluations:
            out[sid] = scoring.Status.FAILED
        else:
            out[sid] = scoring.Status.GENERATED
    return out


async def latest_run(
    session: AsyncSession, *, dataset_source: str
) -> StrategyLabDiscoveryRun | None:
    return (
        await session.execute(
            select(StrategyLabDiscoveryRun)
            .where(
                StrategyLabDiscoveryRun.dataset_source == dataset_source,
                StrategyLabDiscoveryRun.finished_at.is_not(None),
            )
            .order_by(StrategyLabDiscoveryRun.finished_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
