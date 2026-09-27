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
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.labs.graduation import config, sources
from app.labs.graduation.features import FeatureEngine
from app.labs.graduation.models import GradCurveSample, GradToken
from app.labs.graduation.tournament import Tournament
from app.workers.celery_app import celery_app

logger = get_logger(__name__)

TASK_NAME = "app.labs.graduation.scheduler.graduation_prune_tick"
FEATURES_TASK = "app.labs.graduation.scheduler.graduation_features_tick"
PAPER_TASK = "app.labs.graduation.scheduler.graduation_paper_tick"
FLOWS_TASK = "app.labs.graduation.scheduler.graduation_flows_tick"
#: Coins read per pass, and how often: ~45 Helius credits a coin, so a full
#: backfill of a few hundred trades takes about an hour and then keeps pace.
FLOWS_PER_PASS = 10
FLOWS_INTERVAL_SECONDS = 120
RUGS_TASK = "app.labs.graduation.scheduler.graduation_rugs_tick"
#: Graduations judged per pass: ~10 s of index reads on production at 200.
RUGS_PER_PASS = 200
RUGS_INTERVAL_SECONDS = 120
#: Rugged = the first hour's last price on its own pool under a fifth of its
#: first (see `GradRugVerdict`).
RUG_KEEPS = Decimal("0.2")
RUG_HOUR = timedelta(minutes=60)
_RUG_SQL = text("""
    with p as (select * from unnest(cast(:mints as text[]), cast(:pools as text[]))
               as p(mint, pool))
    select p.mint, f.price_native as first, l.price_native as last,
           enough.ok is not null as enough
    from p
    join grad_migrations m on m.mint = p.mint
    left join lateral (
        select price_native from grad_postgrad_samples s
        where s.mint = p.mint and s.pair_address = p.pool and s.price_native > 0
          and s.ts <= m.ts + interval '60 minutes'
        order by s.ts limit 1) f on true
    left join lateral (
        select price_native from grad_postgrad_samples s
        where s.mint = p.mint and s.pair_address = p.pool and s.price_native > 0
          and s.ts <= m.ts + interval '60 minutes'
        order by s.ts desc limit 1) l on true
    left join lateral (
        select 1 as ok from grad_postgrad_samples s
        where s.mint = p.mint and s.pair_address = p.pool and s.price_native > 0
          and s.ts <= m.ts + interval '60 minutes'
        order by s.ts offset 4 limit 1) enough on true""")
#: Held for the length of one paper tick. "GRAD", as a number.
PAPER_LOCK_KEY = 0x47524144


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
            # One tick at a time. At a three-second cadence a slow tick can still
            # be running when the next begins; both would fill the same
            # graduation, and the (book, mint) constraint would then roll back
            # the whole second tick, its closes included.
            if not await session.scalar(
                    select(func.pg_try_advisory_xact_lock(PAPER_LOCK_KEY))):
                return {"skipped": "graduation_paper_tick_running"}
            # Every arm, one clock, one commit: they see the same graduations
            # at the same instant, which is what makes them comparable.
            result = await Tournament(session, now=datetime.now(UTC),
                                      pool_reader=sources.pool_now,
                                      operator_reader=sources.operators_now,
                                      tx_reader=sources.pool_txs_now,
                                      money_checks=True).tick()
            await session.commit()
            return result
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


@celery_app.task(name=FLOWS_TASK)
def graduation_flows_tick() -> dict[str, Any]:
    from app.workers.runtime import run_async

    return run_async(flows_tick())


async def flows_tick() -> dict[str, Any]:
    """Read who traded each closed Karthik's-arm coin, graduation to our sell.

    Read-only on the chain; writes one `grad_trade_flows` row per coin. A coin
    whose read fails is simply left for the next pass.
    """
    if not config.enabled():
        return {"skipped": "graduation_disabled"}
    from app.core.config import settings

    if not settings.helius_configured:
        return {"skipped": "helius_not_configured"}
    try:
        async with SessionFactory() as session:
            return await flows_pass(session, now=datetime.now(UTC))
    except Exception:  # containment is the point: never raise into the beat
        logger.exception("graduation_flows_failed")
        return {"error": "graduation_flows_failed"}


async def flows_pass(session: AsyncSession, *, now: datetime,
                     rpc: Any = None) -> dict[str, Any]:
    from app.core.config import settings
    from app.labs.graduation.models import GradOperator, GradPaperPosition, GradTradeFlow
    from app.labs.graduation.tournament import graduation_pool

    start = next(s.start for s in config.FRESH_BOOKS if s.book == "KARTHIK_QUIET_5M")
    done = select(GradTradeFlow.mint)
    todo = (await session.execute(
        select(GradPaperPosition)
        .where(GradPaperPosition.book == "KARTHIK_QUIET_5M",
               GradPaperPosition.opened_at >= start,
               GradPaperPosition.closed_at.is_not(None),
               GradPaperPosition.closed_at <= now - timedelta(seconds=60),
               GradPaperPosition.mint.not_in(done))
        .order_by(GradPaperPosition.closed_at.desc())
        .limit(FLOWS_PER_PASS))).scalars().all()
    if not todo:
        return {"read": 0}
    mints = [p.mint for p in todo]
    ids = {m: set(i or []) for m, i in (await session.execute(
        select(GradOperator.mint, GradOperator.ids)
        .where(GradOperator.mint.in_(mints)))).all()}
    creators = dict((await session.execute(
        select(GradToken.mint, GradToken.creator).where(GradToken.mint.in_(mints)))).all())
    exclude = frozenset(k for k in (settings.REAL_WALLET_PUBLIC_KEY.strip(),) if k)

    own_rpc = rpc is None
    if own_rpc:
        from app.services.rpc.standard import StandardSolanaRPC

        rpc = StandardSolanaRPC(rpc_url=settings.HELIUS_RPC_URL)
        await rpc.start()
    read = 0
    try:
        for p in todo:
            insiders = frozenset(ids.get(p.mint, set())
                                 | ({creators[p.mint]} if creators.get(p.mint) else set()))
            since = p.graduated_at or p.opened_at
            try:
                f = await sources.pool_flows(rpc, graduation_pool(p.mint), since, p.closed_at,
                                             insiders=insiders, exclude=exclude)
            except Exception as exc:   # left for the next pass
                logger.info("graduation_flows_unread", mint=p.mint, error=type(exc).__name__)
                continue
            usd = Decimal(p.sol_usd_at_open)
            cents = Decimal("0.01")
            session.add(GradTradeFlow(
                mint=p.mint, window_from=since, window_to=p.closed_at,
                insiders_known=len(insiders),
                insider_buy_usd=(Decimal(str(f.insider_buy)) * usd).quantize(cents),
                insider_sell_usd=(Decimal(str(f.insider_sell)) * usd).quantize(cents),
                other_buy_usd=(Decimal(str(f.other_buy)) * usd).quantize(cents),
                other_sell_usd=(Decimal(str(f.other_sell)) * usd).quantize(cents),
                other_buyers=f.other_buyers, swaps=f.swaps))
            read += 1
        await session.commit()
    finally:
        if own_rpc:
            await rpc.close()
    logger.info("graduation_flows_read", read=read, of=len(todo))
    return {"read": read, "of": len(todo)}


@celery_app.task(name=RUGS_TASK)
def graduation_rugs_tick() -> dict[str, Any]:
    from app.workers.runtime import run_async

    return run_async(rugs_tick())


async def rugs_tick() -> dict[str, Any]:
    if not config.enabled():
        return {"skipped": "graduation_disabled"}
    try:
        async with SessionFactory() as session:
            return await rugs_pass(session, now=datetime.now(UTC))
    except Exception:  # containment is the point: never raise into the beat
        logger.exception("graduation_rugs_failed")
        return {"error": "graduation_rugs_failed"}


async def rugs_pass(session: AsyncSession, *, now: datetime) -> dict[str, Any]:
    """Judge every graduation since Karthik's book opened whose first hour is
    over, oldest first, once each. Read-only on the samples."""
    from app.labs.graduation.models import GradMigration, GradRugVerdict
    from app.labs.graduation.tournament import graduation_pool

    start = next(s.start for s in config.FRESH_BOOKS if s.book == "KARTHIK_QUIET_5M")
    todo = (await session.execute(
        select(GradMigration.mint, GradMigration.ts)
        .where(GradMigration.ts >= start,
               GradMigration.ts <= now - RUG_HOUR - timedelta(minutes=5),
               GradMigration.mint.not_in(select(GradRugVerdict.mint)))
        .order_by(GradMigration.ts).limit(RUGS_PER_PASS))).all()
    if not todo:
        return {"judged": 0}
    mints = [m for m, _ in todo]
    found = {r.mint: r for r in await session.execute(
        _RUG_SQL, {"mints": mints, "pools": [graduation_pool(m) for m in mints]})}
    rugged = 0
    for mint, ts in todo:
        r = found.get(mint)
        measured = bool(r and r.enough and r.first and r.last)
        rug = measured and Decimal(r.last) < Decimal(r.first) * RUG_KEEPS
        rugged += rug
        session.add(GradRugVerdict(mint=mint, graduated_at=ts, measured=measured, rugged=rug))
    await session.commit()
    logger.info("graduation_rugs_judged", judged=len(todo), rugged=rugged)
    return {"judged": len(todo), "rugged": rugged}


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
celery_app.conf.beat_schedule.setdefault("graduation-lab-rugs", {
    "task": RUGS_TASK,
    "schedule": float(RUGS_INTERVAL_SECONDS),
})
celery_app.conf.beat_schedule.setdefault("graduation-lab-flows", {
    "task": FLOWS_TASK,
    "schedule": float(FLOWS_INTERVAL_SECONDS),
})
celery_app.conf.beat_schedule.setdefault("graduation-lab-paper", {
    "task": PAPER_TASK,
    "schedule": float(config.PAPER_INTERVAL_SECONDS),
})
