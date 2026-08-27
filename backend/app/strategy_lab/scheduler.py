"""Celery entry point for continuous research. **Off unless explicitly enabled.**

One task, on a five-minute beat. It settles open simulated positions against
observations that arrived since the last tick, then offers the strategies any
canonical opportunity they have not seen. Both halves are idempotent, so a
missed beat costs freshness and never correctness — the next tick does exactly
the work the missed one would have.

── WHY THIS CANNOT DEGRADE ANYTHING ─────────────────────────────────────────

  * **It reads the same rows Radar and the market collector already wrote.** It
    adds no provider call, no RPC, and no enrichment work.
  * **Its work is bounded per tick**: `FORWARD_BATCH` new opportunities and the
    open positions, which is capped by the strategies' own capital ($1,000 at
    $25 is at most forty per strategy).
  * **It holds its own advisory lock**, so two beats can never evaluate the
    same wallet concurrently and double-book a fill.
  * **It runs last in the beat order it shares**, and its lock is released with
    its transaction, so a slow tick cannot block the paper review.

While `STRATEGY_LAB_MODE` is not `FORWARD_RESEARCH` the task returns
immediately without opening a transaction. Deploying this file therefore
changes nothing until the setting is changed deliberately.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import text

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.strategy_lab import service
from app.strategy_lab.state import LabState
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)

#: Deterministic advisory-lock key, in the same style the paper review uses.
#: ASCII "MEME"/"SLAB" as signed 32-bit integers — not Python's
#: process-randomised `hash()`, which would give a different lock per worker.
LAB_LOCK_NAMESPACE = 0x4D454D45
LAB_LOCK_KEY = 0x534C4142


@celery_app.task(name="app.strategy_lab.scheduler.strategy_lab_tick")
def strategy_lab_tick() -> dict[str, Any]:
    """Advance forward research by one tick. Simulated only; opens no order."""
    return run_async(_tick())


async def _tick() -> dict[str, Any]:
    state = service.current_state()
    if state is not LabState.FORWARD_RESEARCH:
        # Checked before a session is opened: a disabled lab should cost a
        # function call, not a connection.
        return {"skipped": True, "state": state.value}

    async with SessionFactory() as session:
        acquired = (
            await session.execute(
                text("SELECT pg_try_advisory_xact_lock(:ns, :key)"),
                {"ns": LAB_LOCK_NAMESPACE, "key": LAB_LOCK_KEY},
            )
        ).scalar_one()
        if not acquired:
            # A previous tick is still running. Coalesce rather than queue: the
            # work is idempotent, so the next beat picks up whatever is left.
            return {"skipped": True, "reason": "tick already running"}

        tick = await service.evaluate_forward(
            session,
            starting_capital=Decimal(str(settings.STRATEGY_LAB_STARTING_CAPITAL)),
        )

    logger.info(
        "strategy_lab_tick",
        extra={
            "state": tick.state,
            "new_opportunities": tick.new_opportunities,
            "opened": tick.positions_opened,
            "closed": tick.positions_closed,
            "fills": tick.fills_booked,
            "refusals": tick.refusals,
            "wallets": tick.wallets,
        },
    )
    return {
        "skipped": False,
        "state": tick.state,
        "new_opportunities": tick.new_opportunities,
        "positions_opened": tick.positions_opened,
        "positions_closed": tick.positions_closed,
        "fills_booked": tick.fills_booked,
        "refusals": tick.refusals,
        "wallets": tick.wallets,
    }
