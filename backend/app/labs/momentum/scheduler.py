"""The lab's beat tasks. Declared in `app/workers/celery_app.py` (beat never
imports lab modules, so an entry registered here would never fire).

All three return before opening a session while `LAB_MOMENTUM_ENABLED` is off,
and none raises into the beat: the lab is instrumentation.

Without a worker: `python -m app.labs.momentum universe|tick|prune`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.labs.momentum import config
from app.labs.momentum.lab import MomentumLab
from app.labs.momentum.sources import Feeds
from app.workers.celery_app import celery_app

logger = get_logger(__name__)

TICK_TASK = "app.labs.momentum.scheduler.momentum_tick"
UNIVERSE_TASK = "app.labs.momentum.scheduler.momentum_universe"
PRUNE_TASK = "app.labs.momentum.scheduler.momentum_prune"
#: One lock for all three: a universe refresh must not rewrite the pool list
#: while a tick is marking it.
LOCK_KEY = 0x4D4F4D30  # "MOM0"


async def run(step: str) -> dict[str, Any]:
    """One step, under the lab's lock, committed or not at all."""
    if not config.enabled():
        return {"skipped": "momentum_lab_disabled"}
    try:
        async with SessionFactory() as session:
            pace = config.RESOLVE_CALLS_PER_MINUTE if step == "universe" else None
            async with Feeds(dex_per_minute=pace) as feeds:
                lab = MomentumLab(session, feeds=feeds)
                # The universe's HTTP half runs BEFORE the lock: minutes of
                # lookups must not stall the ticks.
                plan = await lab.plan_universe() if step == "universe" else None
                if step == "universe" and plan is None:
                    return {"listed": 0, "skipped": "no_lists_answered"}
                # A tick that finds the lock taken is skipped: the next one is
                # 30s away. The other steps WAIT for it — a tick holds it for
                # seconds, and a skipped refresh would cost half an hour.
                if step != "tick":
                    await session.execute(select(func.pg_advisory_xact_lock(LOCK_KEY)))
                elif not await session.scalar(
                        select(func.pg_try_advisory_xact_lock(LOCK_KEY))):
                    return {"skipped": "momentum_lab_busy"}
                if step == "tick":
                    result = await lab.tick()
                elif plan is not None:
                    result = await lab.apply_universe(plan)
                else:
                    result = await lab.prune()
            await session.commit()
            return result
    except Exception:  # containment: never raise into the beat
        logger.exception("momentum_lab_failed", step=step)
        return {"error": f"momentum_{step}_failed"}


@celery_app.task(name=TICK_TASK)
def momentum_tick() -> dict[str, Any]:
    from app.workers.runtime import run_async

    return run_async(run("tick"))


@celery_app.task(name=UNIVERSE_TASK)
def momentum_universe() -> dict[str, Any]:
    from app.workers.runtime import run_async

    return run_async(run("universe"))


@celery_app.task(name=PRUNE_TASK)
def momentum_prune() -> dict[str, Any]:
    from app.workers.runtime import run_async

    return run_async(run("prune"))
