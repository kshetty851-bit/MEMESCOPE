"""Scoring maintenance jobs.

The enrichment worker is the fast path: it scores what it has just enriched.
These jobs are the safety net and the migration tooling.

  * `score_sweep` covers everything the fast path can miss - the crash window
    between the enrichment commit and the scoring commit, deploys, restarts,
    and tokens whose scoring transaction failed. The enrichment worker learned
    this lesson already (`ENRICHMENT_BACKFILL_INTERVAL_SECONDS`); a startup-only
    reconciliation leaves tokens orphaned until someone notices.
  * `rescore_tokens` recomputes under a model version. Possible at all only
    because scoring is a pure function of stored data, so a past score can be
    reproduced rather than merely overwritten.
  * `prune_score_history` keeps append-only history from growing without bound.

All three commit their own transactions and publish events only afterwards,
matching the worker.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.config import settings
from app.core.events import publish_score_events
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.repositories.score import ScoreHistoryRepository, ScoreRepository
from app.services.scoring.models.registry import get_model
from app.services.scoring.service import TokenScoringService
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)


@celery_app.task(name="app.workers.scoring_tasks.score_sweep")
def score_sweep(limit: int | None = None) -> dict[str, Any]:
    """Score tokens the fast path missed, left stale, or scored under an old model."""
    return run_async(_score_sweep(limit))


async def _score_sweep(limit: int | None = None) -> dict[str, Any]:
    if not settings.FEATURE_AI_SCORING_ENABLED:
        return {"skipped": "scoring_disabled"}

    batch_limit = limit or settings.SCORING_SWEEP_BATCH_LIMIT
    now = datetime.now(UTC)
    model = get_model()

    async with SessionFactory() as session:
        service = TokenScoringService(session, model=model)
        scores = ScoreRepository(session)

        missing = list(await scores.mints_without_scores(limit=batch_limit))
        stale = await service.find_stale(now=now, limit=batch_limit)
        outdated = list(
            await scores.outdated_model_mints(model_version=model.version, limit=batch_limit)
        )

        # One pass over the union: a token can easily be both stale and
        # outdated, and scoring it twice in a cycle would write two history rows
        # describing the same evaluation.
        targets = list(dict.fromkeys([*missing, *stale, *outdated]))[:batch_limit]
        if not targets:
            return {"missing": 0, "stale": 0, "outdated": 0, "scored": 0}

        outcome = await service.score_mints(targets, now=now)
        await session.commit()

    published = await publish_score_events(outcome.events)

    logger.info(
        "score_sweep_completed",
        missing=len(missing),
        stale=len(stale),
        outdated=len(outdated),
        **outcome.as_dict(),
        events=published,
    )
    return {
        "missing": len(missing),
        "stale": len(stale),
        "outdated": len(outdated),
        **outcome.as_dict(),
        "events": published,
    }


@celery_app.task(name="app.workers.scoring_tasks.rescore_tokens")
def rescore_tokens(
    model_version: str | None = None,
    after_mint: str | None = None,
    limit: int | None = None,
    publish: bool = False,
) -> dict[str, Any]:
    """Recompute scores for one resumable page of tokens.

    Returns `next_cursor`, so a promotion drains the table page by page instead
    of holding one enormous transaction open. Events are suppressed by default:
    a backfill is not news, and announcing thousands of score changes at once
    would flood the Observatory Log with a maintenance operation.
    """
    return run_async(_rescore_tokens(model_version, after_mint, limit, publish))


async def _rescore_tokens(
    model_version: str | None,
    after_mint: str | None,
    limit: int | None,
    publish: bool,
) -> dict[str, Any]:
    # Resolved before any work: an unknown version must fail the task outright
    # rather than silently rescoring under the active model.
    model = get_model(model_version)
    batch_limit = limit or settings.SCORING_RESCORE_BATCH_LIMIT
    now = datetime.now(UTC)

    async with SessionFactory() as session:
        service = TokenScoringService(session, model=model)
        mints = list(
            await ScoreRepository(session).scored_mints_page(
                after_mint=after_mint, limit=batch_limit
            )
        )
        if not mints:
            return {"model_version": model.version, "scored": 0, "next_cursor": None}

        outcome = await service.score_mints(mints, now=now)
        await session.commit()

    if publish and outcome.events:
        await publish_score_events(outcome.events)

    next_cursor = mints[-1] if len(mints) == batch_limit else None
    logger.info(
        "rescore_completed",
        model_version=model.version,
        next_cursor=next_cursor,
        **outcome.as_dict(),
    )
    return {
        "model_version": model.version,
        **outcome.as_dict(),
        "next_cursor": next_cursor,
    }


@celery_app.task(name="app.workers.scoring_tasks.prune_score_history")
def prune_score_history(retention_days: int | None = None) -> dict[str, Any]:
    """Thin score history older than the retention window to hourly samples."""
    return run_async(_prune_score_history(retention_days))


async def _prune_score_history(retention_days: int | None = None) -> dict[str, Any]:
    days = retention_days or settings.SCORING_HISTORY_RETENTION_DAYS
    cutoff = datetime.now(UTC) - timedelta(days=days)

    async with SessionFactory() as session:
        deleted = await ScoreHistoryRepository(session).prune_before(cutoff=cutoff)
        await session.commit()

    logger.info("score_history_pruned", deleted=deleted, retention_days=days)
    return {"deleted": deleted, "retention_days": days}
