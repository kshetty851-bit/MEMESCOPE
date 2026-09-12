"""The lab's beat tasks: build features, and prune tokens that never graduated.

The RECORDER is not a beat task — it is a long-lived process that holds a
websocket open, and Celery is the wrong shape for that. Run it with
`python -m app.labs.graduation record`. This module is only the periodic
tidying behind it.

The schedule REGISTERS ITSELF on import, with `setdefault`, so an operator who
prefers to name it in `app/workers/celery_app.py` wins and there is never a
second entry for the same task.

With the flag down the task returns before it opens a session.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.labs.graduation import config
from app.labs.graduation.features import FeatureEngine
from app.labs.graduation.models import GradCurveSample, GradToken
from app.labs.graduation.paper import PaperBook
from app.workers.celery_app import celery_app

logger = get_logger(__name__)

TASK_NAME = "app.labs.graduation.scheduler.graduation_prune_tick"
FEATURES_TASK = "app.labs.graduation.scheduler.graduation_features_tick"
PAPER_TASK = "app.labs.graduation.scheduler.graduation_paper_tick"


@celery_app.task(name=TASK_NAME)
def graduation_prune_tick() -> dict[str, Any]:
    from app.workers.runtime import run_async

    return run_async(prune_tick())


async def prune_tick() -> dict[str, Any]:
    """One prune pass. Returns what it did, so a beat log is readable."""
    if not config.enabled():
        return {"skipped": "graduation_disabled"}
    try:
        async with SessionFactory() as session:
            result = await prune(session, now=datetime.now(UTC))
            await session.commit()
            return result
    except Exception:  # containment is the point: never raise into the beat
        logger.exception("graduation_prune_failed")
        return {"error": "graduation_prune_failed"}


@celery_app.task(name=FEATURES_TASK)
def graduation_features_tick() -> dict[str, Any]:
    from app.workers.runtime import run_async

    return run_async(features_tick())


async def features_tick(*, recompute: bool = False) -> dict[str, Any]:
    """One feature pass over graduates whose outcome window has closed.

    Deliberately NOT chained behind the pruner: they touch disjoint rows (the
    pruner only ever deletes non-graduates, and this only ever reads
    graduates), so ordering them would buy nothing and a failure in one would
    delay the other.
    """
    if not config.enabled():
        return {"skipped": "graduation_disabled"}
    try:
        async with SessionFactory() as session:
            result = await FeatureEngine(session).run(
                now=datetime.now(UTC), recompute=recompute)
            await session.commit()
            return result
    except Exception:  # containment is the point: never raise into the beat
        logger.exception("graduation_features_failed")
        return {"error": "graduation_features_failed"}


@celery_app.task(name=PAPER_TASK)
def graduation_paper_tick() -> dict[str, Any]:
    from app.workers.runtime import run_async

    return run_async(paper_tick())


async def paper_tick() -> dict[str, Any]:
    """One pass of the forward paper book.

    Gated by `LAB_GRADUATION_PAPER_ENABLED` **on top of** the lab flag, so the
    recorder can run for weeks before anything opens a position.
    """
    if not config.paper_enabled():
        return {"skipped": "graduation_paper_disabled"}
    try:
        async with SessionFactory() as session:
            # Both books, one clock, one commit: they see the same graduations
            # at the same instant, which is what makes them comparable.
            now = datetime.now(UTC)
            results = {book: await PaperBook(session, book=book, now=now).tick()
                       for book in config.PAPER_BOOKS}
            await session.commit()
            return results
    except Exception:  # containment: never raise into the beat
        logger.exception("graduation_paper_failed")
        return {"error": "graduation_paper_failed"}


async def prune(session: AsyncSession, *, now: datetime) -> dict[str, int]:
    """Delete the curve samples of tokens that never graduated, keeping the row.

    What survives is the `grad_tokens` aggregates — max progress, sample count,
    peak market cap, the timestamps — and every `grad_checkpoints` row. The
    checkpoints ARE the aggregate the lab exists for: "how many tokens reached
    90% and died there" must stay answerable for ever, and it costs at most
    five rows a token. The poll-by-poll reserve series is what does not
    survive, and it is the only thing that grows without bound.

    `grad_postgrad_samples` is never touched: it only exists for tokens that
    DID graduate, and a graduate is never pruned — by EITHER graduation signal,
    which is the subtlety this query gets right.

    Bounded to `PRUNE_MAX_TOKENS_PER_RUN` per pass. The worker's soft time
    limit is 540 seconds and it kills a task BEFORE it commits, so an unbounded
    delete would do its work and then lose it.
    """
    # The cutoff is computed in PYTHON, not as `column - timedelta`: SQLAlchemy
    # binds a type from the LEFT operand, so `GradToken.first_seen_at -
    # timedelta(...)` compiles, runs, raises nothing and matches zero rows.
    cutoff = now - timedelta(hours=config.PRUNE_AFTER_HOURS)
    # "Never graduated" must mean what the rest of the lab means by it. There
    # are TWO independent graduation signals — the websocket migration message
    # (`migrated_at`) and the chain's own `complete` flag — and either may
    # arrive first, or alone. Testing only `migrated_at` would prune the curve
    # series of a token that demonstrably filled its curve, just because the
    # feed never mentioned it. That series is the whole input to `features.py`.
    graduated_on_chain = (
        select(GradCurveSample.mint)
        .where(GradCurveSample.mint == GradToken.mint,
               GradCurveSample.complete.is_(True))
        .exists()
    )
    mints = (await session.scalars(
        select(GradToken.mint)
        .where(
            GradToken.first_seen_at < cutoff,
            GradToken.migrated_at.is_(None),
            ~graduated_on_chain,
            GradToken.pruned_at.is_(None),
        )
        .order_by(GradToken.first_seen_at)
        .limit(config.PRUNE_MAX_TOKENS_PER_RUN)
    )).all()
    if not mints:
        return {"tokens": 0, "samples_deleted": 0}

    result = await session.execute(
        delete(GradCurveSample).where(GradCurveSample.mint.in_(mints)))
    await session.execute(
        update(GradToken).where(GradToken.mint.in_(mints)).values(pruned_at=now))
    # `rowcount` is on the CursorResult a DELETE actually returns; the declared
    # `Result` does not carry it.
    deleted = getattr(result, "rowcount", 0) or 0
    logger.info("graduation_pruned", tokens=len(mints), samples=deleted)
    return {"tokens": len(mints), "samples_deleted": deleted}


#: `setdefault`, so an operator who names either in `celery_app.py` wins over
#: this and there is never a second entry for the same task.
celery_app.conf.beat_schedule.setdefault("graduation-lab-prune", {
    "task": TASK_NAME,
    "schedule": float(config.PRUNE_INTERVAL_SECONDS),
})
celery_app.conf.beat_schedule.setdefault("graduation-lab-features", {
    "task": FEATURES_TASK,
    "schedule": float(config.FEATURES_INTERVAL_SECONDS),
})
celery_app.conf.beat_schedule.setdefault("graduation-lab-paper", {
    "task": PAPER_TASK,
    "schedule": float(config.PAPER_INTERVAL_SECONDS),
})
