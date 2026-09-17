"""Serialized real-wallet beat tasks: the dry-run review, the driver, the runner."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import func, select

from app.core.config import settings
from app.core.events import publish_live_update
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.models.lab import LabDecision
from app.models.real_wallet_execution import RealWalletLiveIntent
from app.models.real_wallet_execution import RealWalletPosition
from app.paper.service import utcnow
from app.real_wallet.autotrade import AutotradeSwitchService
from app.real_wallet.driver import RealWalletDriver
from app.real_wallet.dry_run import RealWalletDryRunService
from app.real_wallet.executor import RealWalletExecutor
from app.real_wallet.exit_driver import RealWalletExitDriver
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)
DRY_RUN_LOCK_NAMESPACE = 0x4D454D45
DRY_RUN_LOCK_KEY = 0x44525952
#: Its own key, so a driver tick and a dry-run review never block each other.
DRIVER_LOCK_KEY = 0x44525652
#: And the runner's, for the same reason.
EXECUTOR_LOCK_KEY = 0x45584543
#: And the exit driver's.
EXIT_LOCK_KEY = 0x45584954
#: And the self-paced exit loop's, so it never blocks the minute tasks.
FAST_EXIT_LOCK_KEY = 0x46415354
#: And the empty-account sweep's.
CLOSE_LOCK_KEY = 0x434C4F53

#: States that still have somewhere to go. Terminal ones are skipped rather than
#: queried, so a finished book does not grow the work every minute.
UNFINISHED_STATES = ("created", "safety_approved", "order_created", "submitted")


@celery_app.task(name="app.real_wallet.scheduler.real_wallet_dry_run")
def real_wallet_dry_run() -> dict[str, Any]:
    return run_async(_real_wallet_dry_run())


async def _real_wallet_dry_run() -> dict[str, Any]:
    if not settings.FEATURE_REAL_WALLET_DRY_RUN_ENABLED:
        return {"skipped": "dry_run_feature_disabled"}
    if settings.REAL_WALLET_EXECUTION_MODE != "dry_run":
        return {"skipped": "execution_mode_disabled"}
    async with SessionFactory() as session:
        acquired = await session.scalar(
            select(func.pg_try_advisory_xact_lock(DRY_RUN_LOCK_NAMESPACE, DRY_RUN_LOCK_KEY))
        )
        if not acquired:
            await session.rollback()
            return {"skipped": "dry_run_already_running"}
        outcome = await RealWalletDryRunService(session).review(now=utcnow())
        await session.commit()
    await publish_live_update("real_wallet.dry_run.changed")
    logger.info("real_wallet_dry_run", **outcome.as_dict())
    return outcome.as_dict()


def request_dry_run(*, trigger: str) -> None:
    """Queue the same dry-run after Radar moves; never run inline."""
    if not settings.FEATURE_REAL_WALLET_DRY_RUN_ENABLED:
        return
    if settings.REAL_WALLET_EXECUTION_MODE != "dry_run":
        return
    try:
        real_wallet_dry_run.delay()
    except Exception:  # pragma: no cover - broker failure must not roll back Radar.
        logger.warning("real_wallet_dry_run_enqueue_failed", trigger=trigger, exc_info=True)


@celery_app.task(name="app.real_wallet.scheduler.real_wallet_driver_tick")
def real_wallet_driver_tick() -> dict[str, Any]:
    """Give the driver a heartbeat.

    Without this nothing ever calls it: the operator could nominate a strategy,
    press START, and watch a switch that was on while no intent was ever created.

    The task adds no authority of its own. `RealWalletDriver.tick` is a chain of
    refusals — switch off, no strategy, no wallet, no entry size, kill switch,
    unreadable balance, policy bounds, no fresh decision, mint already traded —
    and the default state of the switch refuses at the first of them. Creating an
    intent is not spending: every barrier downstream of it still stands.

    Every minute, matching the Lab's beat, because a Lab decision is actionable
    for ten minutes and a slower tick would spend most of that shelf life asleep.
    """
    return run_async(_real_wallet_driver_tick())


async def _real_wallet_driver_tick() -> dict[str, Any]:
    try:
        async with SessionFactory() as session:
            # One driver at a time. The intent's idempotency key already stops a
            # duplicate row, but two concurrent ticks would each read the open
            # position count before either wrote, and the policy would be
            # counting a book that no longer exists.
            acquired = await session.scalar(
                select(func.pg_try_advisory_xact_lock(
                    DRY_RUN_LOCK_NAMESPACE, DRIVER_LOCK_KEY
                ))
            )
            if not acquired:
                await session.rollback()
                return {"skipped": "driver_already_running"}
            outcome = await RealWalletDriver(session).tick(now=utcnow())
            await session.commit()
    except Exception:
        # Contained like the Lab's: a driver failure must not stop the beat that
        # also runs the kill switch's neighbours.
        logger.exception("real_wallet_driver_tick_failed")
        return {"failed": True}
    if outcome.created:
        logger.warning("real_wallet_driver_tick", **outcome.as_dict())
    return outcome.as_dict()


@celery_app.task(name="app.real_wallet.scheduler.real_wallet_executor_tick")
def real_wallet_executor_tick() -> dict[str, Any]:
    """Walk every unfinished intent forward by one state.

    The driver creates intents and nothing moved them, so an intent would sit at
    CREATED for ever. `advance` performs at most one transition per call, so an
    intent needs several ticks to reach a terminal state — which is exactly what
    makes a crash mid-flight recoverable: every state is a committed row.

    The runner owns no authority. `LiveSubmissionGuard` and
    `ExecutionTransportPolicy` decide whether anything may be submitted, and on
    mainnet both still refuse, so a complete walk today ends in a recorded
    refusal rather than a transaction.
    """
    return run_async(_real_wallet_executor_tick())


async def _real_wallet_executor_tick() -> dict[str, Any]:
    outcomes: list[dict[str, object]] = []
    try:
        async with SessionFactory() as session:
            acquired = await session.scalar(
                select(func.pg_try_advisory_xact_lock(
                    DRY_RUN_LOCK_NAMESPACE, EXECUTOR_LOCK_KEY
                ))
            )
            if not acquired:
                await session.rollback()
                return {"skipped": "executor_already_running"}
            ids = list((await session.scalars(
                select(RealWalletLiveIntent.id)
                .where(RealWalletLiveIntent.state.in_(UNFINISHED_STATES))
                .order_by(RealWalletLiveIntent.created_at)
            )).all())
            executor = RealWalletExecutor(session)
            for intent_id in ids:
                # One intent's failure must not strand the rest of the book, and
                # in particular must not stop a SUBMITTED intent from being
                # reconciled — that is the one step that cannot wait.
                try:
                    outcome = await executor.advance(intent_id, now=utcnow())
                    outcomes.append(outcome.as_dict())
                except Exception:
                    logger.exception("real_wallet_advance_failed",
                                     intent_id=str(intent_id))
            await session.commit()
    except Exception:
        logger.exception("real_wallet_executor_tick_failed")
        return {"failed": True}
    advanced = [o for o in outcomes if o.get("changed")]
    if advanced:
        logger.warning("real_wallet_executor_tick", advanced=len(advanced),
                       states=[o["state"] for o in advanced])
    return {"examined": len(outcomes), "advanced": len(advanced),
            "outcomes": outcomes}


@celery_app.task(name="app.real_wallet.scheduler.real_wallet_exit_tick")
def real_wallet_exit_tick() -> dict[str, Any]:
    """Mark every open real position and request the exit its rules call for.

    Without this the wallet buys and never sells: nothing else in production
    creates a SELL intent, so no profit is ever realised and nothing compounds.

    It adds no authority. Positions exit by the rules they were ENTERED under,
    read from the position rather than from whatever strategy is nominated now,
    and creating a SELL intent is not selling — the order, the signature and the
    submission each keep their own barrier.
    """
    return run_async(_real_wallet_exit_tick())


async def _real_wallet_exit_tick() -> dict[str, Any]:
    try:
        async with SessionFactory() as session:
            acquired = await session.scalar(
                select(func.pg_try_advisory_xact_lock(
                    DRY_RUN_LOCK_NAMESPACE, EXIT_LOCK_KEY
                ))
            )
            if not acquired:
                await session.rollback()
                return {"skipped": "exit_driver_already_running"}
            outcome = await RealWalletExitDriver(session).tick(now=utcnow())
            await session.commit()
    except Exception:
        # Contained like the others. An exit driver that raises into beat would
        # take down the tasks that mark the rest of the book with it.
        logger.exception("real_wallet_exit_tick_failed")
        return {"failed": True}
    if outcome.exits_requested:
        logger.warning("real_wallet_exit_tick", **outcome.as_dict())
    return outcome.as_dict()


@celery_app.task(name="app.real_wallet.scheduler.real_wallet_fast_exit_tick")
def real_wallet_fast_exit_tick() -> dict[str, Any]:
    """Run the exit path inside the minute instead of once per minute.

    ## Why this exists

    Beat cannot schedule faster than a minute, and `RealWalletExecutor.advance`
    moves an intent exactly one state per call. A SELL therefore needed one tick
    to be noticed and four more to reach submission: a position bought under a
    five-minute rule was sold at roughly ten.

    For a strategy whose margin is seconds that is not slower, it is fatal.
    Replayed over the graduation lab's own 145 trades, exiting 30s late wiped
    the wallet; drawing the tick phase uniformly across the minute wiped it in
    54% of draws, against $139.54 for the same trades exiting on time.

    ## What it does

    One pass is: ask the exit driver what should leave, then walk every
    unfinished intent as far as it will go — rather than one step and a minute's
    wait. The pass repeats on a short interval until the window closes, and beat
    starts the next one.

    ## What it does not do

    No authority of its own, exactly like its neighbours. It calls the same exit
    driver and the same executor, so the autotrade switch, the kill switches,
    the submission guard and the transport policy are each evaluated where they
    always were. Running more often changes WHEN those refusals happen, never
    whether. With the execution mode at its default it refuses before doing
    anything at all.

    Every pass commits. The window sits far below the 540s soft limit, but a
    task killed mid-window still leaves every decision it already made on disk.
    """
    return run_async(_real_wallet_fast_exit_tick())


async def _locked(session: Any) -> bool:
    """This transaction holds the fast loop's lock AND the executor's.

    The executor's too, so the minute tick never advances an intent this loop is
    part-way through. Both are transaction-scoped and re-entrant, so taking them
    again in a transaction that already holds them succeeds.
    """
    for key in (FAST_EXIT_LOCK_KEY, EXECUTOR_LOCK_KEY):
        if not await session.scalar(select(func.pg_try_advisory_xact_lock(
                DRY_RUN_LOCK_NAMESPACE, key))):
            return False
    return True


async def _drain(session: Any, *, now_fn: Any) -> list[dict[str, object]]:
    """Walk every unfinished intent to a terminal state, not one step of it.

    COMMITTED AFTER EVERY STEP. The executor's contract is that every state is a
    committed row, and the signer depends on it: it is another process and
    reloads the intent by id, so a step still inside this transaction does not
    exist for it. Chained in one transaction, the wallet's first live buy
    (2026-09-17) was refused `intent_not_found`, and every buy or sell this loop
    created would have been. A commit releases the transaction's locks, so they
    are taken again before the next step; if another pass holds them, this one
    stops and leaves the rest to it.
    """
    moved: list[dict[str, object]] = []
    if not await _locked(session):
        return moved
    ids = list((await session.scalars(
        select(RealWalletLiveIntent.id)
        .where(RealWalletLiveIntent.state.in_(UNFINISHED_STATES))
        .order_by(RealWalletLiveIntent.created_at)
    )).all())
    executor = RealWalletExecutor(session)
    for intent_id in ids:
        for _ in range(settings.REAL_WALLET_FAST_EXIT_MAX_STEPS):
            # One intent's failure must not strand the rest of the book — and in
            # particular must not stop a SUBMITTED intent being reconciled.
            try:
                outcome = await executor.advance(intent_id, now=now_fn())
            except Exception:
                logger.exception("real_wallet_fast_advance_failed",
                                 intent_id=str(intent_id))
                break
            if not outcome.changed:
                break
            moved.append(outcome.as_dict())
            await session.commit()
            if not await _locked(session):
                return moved
    return moved


async def _has_work() -> bool:
    """Is there anything for the loop to pace itself over?

    Checked once per beat rather than trusted to the execution mode, because
    "disabled" is this setting's default and NOT what a configured wallet runs:
    production sits at `live` with the operator's switch off, so a mode check
    alone would leave a three-second loop polling an empty book for ever on a
    two-core box. Nothing can appear mid-window that this misses — positions are
    created by the driver's own minute tick, and the soonest exit any of them
    can want is its whole hold away.
    """
    async with SessionFactory() as session:
        open_positions = await session.scalar(
            select(func.count()).select_from(RealWalletPosition)
            .where(RealWalletPosition.status == "OPEN"))
        if open_positions:
            return True
        unfinished = await session.scalar(
            select(func.count()).select_from(RealWalletLiveIntent)
            .where(RealWalletLiveIntent.state.in_(UNFINISHED_STATES)))
        if unfinished:
            return True
        # A fresh decision is work too, now that this loop also ENTERS. Without
        # this the fast path would idle through exactly the sixty seconds in
        # which a five-minute strategy has to be filled, and entries would fall
        # back to the once-a-minute beat this exists to replace.
        switch = await AutotradeSwitchService(session).state()
        if not (switch.enabled and switch.nominated_strategy):
            return False
        # The graduation arm's decisions land mid-minute and go stale in sixty
        # seconds, so a loop that only notices them at the next beat buys up to
        # a minute late — measured at a median 55s behind the paper book. While
        # it is the nominated strategy, the loop runs its whole window and the
        # driver looks every pass; the driver's first question is a single
        # query, so an empty pass costs almost nothing.
        from app.labs.graduation.live_spec import BY_ID as GRADUATION

        if switch.nominated_strategy.upper() in GRADUATION:
            return True
        cutoff = utcnow() - RealWalletDriver._decision_age(
            switch.nominated_strategy)
        fresh = await session.scalar(
            select(func.count()).select_from(LabDecision)
            .where(LabDecision.strategy_id == switch.nominated_strategy.upper(),
                   LabDecision.eligible.is_(True),
                   LabDecision.checkpoint_at >= cutoff))
        return bool(fresh)


async def _real_wallet_fast_exit_tick() -> dict[str, Any]:
    if settings.REAL_WALLET_EXECUTION_MODE == "disabled":
        return {"skipped": "execution_mode_disabled"}
    if not await _has_work():
        return {"skipped": "nothing_open"}
    deadline = utcnow().timestamp() + settings.REAL_WALLET_FAST_EXIT_WINDOW_S
    passes = entries = exits = advanced = 0
    while True:
        try:
            async with SessionFactory() as session:
                acquired = await session.scalar(
                    select(func.pg_try_advisory_xact_lock(
                        DRY_RUN_LOCK_NAMESPACE, FAST_EXIT_LOCK_KEY
                    ))
                )
                if not acquired:
                    await session.rollback()
                    return {"skipped": "fast_exit_already_running",
                            "passes": passes}
                # ENTRY, not only exit. The hold runs from the wallet's own
                # fill but the collapse runs from GRADUATION, so a late buy
                # pushes the SELL past the cliff rather than merely delaying
                # it. Replayed over the graduation arm's own 145 trades, a
                # uniform 0-60s entry lag wiped the wallet in 51% of draws and
                # a flat 60s lag in 100%; at 0-15s it is 0%. A once-a-minute
                # driver tick is therefore not a slower version of the right
                # thing for a five-minute hold — it is the wrong thing.
                #
                # No new authority. `RealWalletDriver.tick` creates at most ONE
                # buy intent per call and is a chain of refusals: switch off,
                # no strategy nominated, no wallet, no entry size, kill switch,
                # unreadable balance, policy bounds, no fresh decision, mint
                # already traded. Calling it more often changes WHEN those
                # refuse, never whether — and REAL_WALLET_MAX_OPEN_POSITIONS
                # and MAX_TOTAL_EXPOSURE_USD bound the book however fast this
                # runs.
                bought = await RealWalletDriver(session).tick(now=utcnow())
                outcome = await RealWalletExitDriver(session).tick(now=utcnow())
                moved = await _drain(session, now_fn=utcnow)
                await session.commit()
            passes += 1
            entries += bought.created
            exits += outcome.exits_requested
            advanced += len(moved)
            if bought.created or outcome.exits_requested or moved:
                logger.warning("real_wallet_fast_exit_pass",
                               entries=bought.created,
                               exits=outcome.exits_requested,
                               advanced=len(moved))
        except Exception:
            # Contained like its neighbours: this task shares a beat with the
            # kill switch's, and must not take them down with it.
            logger.exception("real_wallet_fast_exit_tick_failed")
            return {"failed": True, "passes": passes}
        # Checked AFTER a pass, so a zero window still does one — otherwise
        # setting it to 0 would silently disable the exit path entirely.
        if utcnow().timestamp() >= deadline:
            break
        await asyncio.sleep(settings.REAL_WALLET_FAST_EXIT_INTERVAL_S)
    return {"passes": passes, "entries": entries,
            "exits_requested": exits, "advanced": advanced}


@celery_app.task(name="app.real_wallet.scheduler.real_wallet_balance_watch")
def real_wallet_balance_watch() -> dict[str, Any]:
    """Record what the chain says the wallet holds, and whether the rail explains it.

    Every other guard here asks whether a spend may PROCEED. None notices money
    that never used the rail at all — a key used elsewhere, a signature produced
    outside it. The chain balance compared against what the rail did is the only
    evidence for that, and it is the one signal in this file that is security
    rather than operations.

    It writes an observation and decides nothing. HQ turns an unexplained
    decrease into a condition; there is no code path from here to an action.
    """
    return run_async(_real_wallet_balance_watch())


async def _real_wallet_balance_watch() -> dict[str, Any]:
    from app.real_wallet import balance_watch
    from app.services.rpc.standard import StandardSolanaRPC

    try:
        rpc = StandardSolanaRPC(rpc_url=settings.REAL_WALLET_RPC_URL)
        async with rpc:
            async with SessionFactory() as session:
                reading = await balance_watch.observe(session, rpc, now=utcnow())
                await session.commit()
    except Exception:
        logger.exception("real_wallet_balance_watch_failed")
        return {"failed": True}
    return {
        "measured": reading.measured,
        "lamports": reading.lamports,
        "delta_lamports": reading.delta_lamports,
        "unexplained": reading.unexplained,
    }


@celery_app.task(name="app.real_wallet.scheduler.real_wallet_close_empty_accounts")
def real_wallet_close_empty_accounts() -> dict[str, Any]:
    """Return the rent parked in the wallet's empty token accounts.

    Each buy parks ~0.0015 SOL in a new token account and the sell leaves it
    there. This closes the empty ones into the wallet itself — a transaction the
    isolated signer re-inspects and refuses unless the rent goes to the wallet.
    It waits while a trade is in flight and never touches an open position's
    mint; see `account_close`.
    """
    return run_async(_real_wallet_close_empty_accounts())


async def _real_wallet_close_empty_accounts() -> dict[str, Any]:
    from app.real_wallet import account_close

    try:
        async with SessionFactory() as session:
            acquired = await session.scalar(
                select(func.pg_try_advisory_xact_lock(
                    DRY_RUN_LOCK_NAMESPACE, CLOSE_LOCK_KEY
                ))
            )
            if not acquired:
                await session.rollback()
                return {"skipped": "close_sweep_already_running"}
            outcome = await account_close.sweep(session)
            await session.rollback()
    except Exception:
        # Contained like its neighbours: parked rent can wait for the next sweep.
        logger.exception("real_wallet_close_empty_accounts_failed")
        return {"failed": True}
    if outcome.closed or outcome.refused:
        logger.warning("real_wallet_close_empty_accounts", **outcome.as_dict())
    return outcome.as_dict()
