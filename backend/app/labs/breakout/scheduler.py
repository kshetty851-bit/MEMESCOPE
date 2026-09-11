"""The lab's beat task and the candle pass chained behind it.

`breakout-lab-tick` runs the universe refresh, then ENQUEUES the candle
refresh as its own task — the same pattern the Crypto Trend lab uses for its
engine, and the paper wallet for its review after the Radar sweep. Chained
rather than given a beat entry of its own so the candles can never race the
universe they are fetched for; enqueued rather than run inline so a candle
failure cannot roll back a completed universe refresh.

The chain is universe -> candles -> setups -> trader, each enqueued by the
one before it so a later pass can never read data an earlier one has not
written yet, and so a failure in one cannot roll back another's transaction.
The outcomes pass rides on the setups task once a day, behind the daily
candles. The trader is gated by its OWN flag on top of the lab's.

`breakout-lab-tick` has one explicit beat entry in `app/workers/celery_app.py`
(every 15 minutes) and the module is in that file's `include`, exactly as the
Crypto Trend lab does it. The CANDLE task deliberately has no entry of its own.

Fifteen minutes is the UNIVERSE's cadence. The candle pass runs behind every
one of those ticks and sends no request for a timeframe whose bar has not
closed, so the hourly sweep happens once an hour and the daily one once a day
whatever the beat's period — the clock decides, not the schedule. A sweep the
deadline cuts short carries over to the next tick, and `data_health` reports
the tokens still waiting as `starved`.

Both tasks are gated by `BREAKOUT_LAB_ENABLED`, read at call time. With the
flag down the universe task returns before it opens a session or a socket,
and nothing is enqueued.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.labs.breakout import config
from app.labs.breakout.candles import BreakoutCandles, due_timeframes
from app.labs.breakout.setups import OutcomeEngine, SetupEngine
from app.labs.breakout.sources import BreakoutSource
from app.labs.breakout.trader import BreakoutTrader
from app.labs.breakout.universe import BreakoutUniverse
from app.workers.celery_app import celery_app

logger = get_logger(__name__)

TICK_TASK = "app.labs.breakout.scheduler.breakout_lab_tick"
CANDLES_TASK = "app.labs.breakout.scheduler.breakout_candles_tick"
SETUPS_TASK = "app.labs.breakout.scheduler.breakout_setups_tick"
TRADER_TASK = "app.labs.breakout.scheduler.breakout_trader_tick"


@celery_app.task(name=TICK_TASK)
def breakout_lab_tick() -> dict[str, Any]:
    from app.workers.runtime import run_async

    result = run_async(universe_tick())
    enqueue_candles()
    return result


@celery_app.task(name=CANDLES_TASK)
def breakout_candles_tick() -> dict[str, Any]:
    from app.workers.runtime import run_async

    result = run_async(candles_tick())
    enqueue(breakout_setups_tick)
    return result


@celery_app.task(name=SETUPS_TASK)
def breakout_setups_tick() -> dict[str, Any]:
    """Levels -> momentum -> state machine -> snapshots, then the daily
    outcomes pass when its own window has come round."""
    from app.workers.runtime import run_async

    result = run_async(setups_tick())
    enqueue(breakout_trader_tick)
    return result


@celery_app.task(name=TRADER_TASK)
def breakout_trader_tick() -> dict[str, Any]:
    """The paper book. Gated by BOTH flags — the lab's and trading's own."""
    from app.workers.runtime import run_async

    return run_async(trader_tick())


def enqueue(task: Any) -> None:
    """Ask the worker for the next link in the chain. Swallows a broker
    failure: the worst case is a pass that does not happen, and the next tick
    asks again."""
    if not config.enabled():
        return
    try:
        task.delay()
    except Exception:  # pragma: no cover - broker failure path
        logger.warning("breakout_enqueue_failed", task=getattr(task, "name", "?"),
                       exc_info=True)


def enqueue_candles() -> None:
    enqueue(breakout_candles_tick)


async def universe_tick() -> dict[str, Any]:
    """One universe pass, but only when the universe is actually stale.

    The beat runs every 15 minutes because that is the CANDLE cadence.
    Discovery costs ~61 GeckoTerminal calls — two sorts of the ranked list,
    four venues, ten pages each — which at 2.4s spacing is about two and a
    half minutes. Running that four times an hour would spend ten minutes of
    the hour on tokens whose membership cannot change that fast, and starve
    the candle sweep that has to keep up with closing bars.

    So the pass checks `UNIVERSE_REFRESH_SECONDS` first and returns without
    opening a socket the other three times in four. `stale()` existed for
    `data_health` and nothing called it here, which meant the interval was a
    number that did nothing.
    """
    if not config.enabled():
        return {"skipped": "breakout_lab_disabled"}
    try:
        now = datetime.now(UTC)
        async with SessionFactory() as session:
            if not await BreakoutUniverse(session, None).stale(now):  # type: ignore[arg-type]
                return {"phase": "universe", "skipped": "fresh"}
        async with BreakoutSource() as source, SessionFactory() as session:
            result = await BreakoutUniverse(session, source).refresh(now)
            await session.commit()
            return result
    except Exception:  # containment is the point: never raise into the beat
        logger.exception("breakout_universe_tick_failed")
        return {"error": "breakout_universe_tick_failed"}


async def candles_tick() -> dict[str, Any]:
    """One candle pass over the active universe."""
    if not config.enabled():
        return {"skipped": "breakout_lab_disabled"}
    try:
        async with BreakoutSource() as source, SessionFactory() as session:
            result = await BreakoutCandles(session, source).refresh(datetime.now(UTC))
            await session.commit()
            return result
    except Exception:  # containment is the point
        logger.exception("breakout_candles_tick_failed")
        return {"error": "breakout_candles_tick_failed"}


async def setups_tick() -> dict[str, Any]:
    """One setup pass over the active universe, and — once a day, after the
    daily candles have landed — the outcomes pass behind it.

    Reads the database only. A rate-limited candle pass therefore cannot stop
    setups being evaluated on the bars that ARE stored.
    """
    if not config.enabled():
        return {"skipped": "breakout_lab_disabled"}
    try:
        now = datetime.now(UTC)
        async with SessionFactory() as session:
            result = await SetupEngine(session).run(now)
            # The outcomes pass is chained behind the SAME tick the daily
            # candles arrive on, so it always reads a fresh daily series. It
            # is idempotent — `outcome_at` marks what is done — so running it
            # on every tick of that hour costs one query.
            if "day" in due_timeframes(now):
                result["outcomes"] = await OutcomeEngine(session).run(now)
            await session.commit()
            return result
    except Exception:  # containment is the point
        logger.exception("breakout_setups_tick_failed")
        return {"error": "breakout_setups_tick_failed"}


async def trader_tick() -> dict[str, Any]:
    """One paper-trading pass, on the bar the setups pass just evaluated.

    Gated by `BREAKOUT_TRADING_ENABLED` **as well as** the lab flag, so the
    watchlist can run for weeks before anything opens a position.
    """
    if not config.enabled():
        return {"skipped": "breakout_lab_disabled"}
    if not config.trading_enabled():
        return {"skipped": "breakout_trading_disabled"}
    try:
        async with SessionFactory() as session:
            result = await BreakoutTrader(session).run(datetime.now(UTC))
            await session.commit()
            return result
    except Exception:  # containment is the point
        logger.exception("breakout_trader_tick_failed")
        return {"error": "breakout_trader_tick_failed"}


async def outcomes_tick() -> dict[str, Any]:
    """The outcomes pass on its own — what the CLI runs."""
    if not config.enabled():
        return {"skipped": "breakout_lab_disabled"}
    async with SessionFactory() as session:
        result = await OutcomeEngine(session).run(datetime.now(UTC))
        await session.commit()
        return result


async def tick() -> dict[str, Any]:
    """All three passes, in order, in one process — what the CLI runs. The
    worker chains them as three tasks instead; this is the same work without a
    broker."""
    if not config.enabled():
        return {"skipped": "breakout_lab_disabled"}
    return {"universe": await universe_tick(), "candles": await candles_tick(),
            "setups": await setups_tick(), "trader": await trader_tick()}
