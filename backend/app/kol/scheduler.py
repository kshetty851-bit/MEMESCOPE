"""The KOL Lab's beat, and the one-time freezing of its ranking.

The sixth registry on the Compound Lab's service. What is different here is
that the tournament cannot open until there is something to rank: the ranking
is taken ONCE, from data strictly before activation, and the wallets it names
are the ones the lab follows for its whole life.

## Why the ranking is taken once and never refreshed

A ranking recomputed on a schedule would start including the very trades the
lab is making decisions about — the wallet that looks good this afternoon
because the coin it bought this morning ran. Freezing it makes the tournament
a forward test of one dated claim, which is the only version of this that can
be wrong.

## Why it waits

`MIN_RANKED_WALLETS` and the ranking's own `MIN_EARLY_BUYS` mean nothing
happens until the collector has produced real history — roughly a week. The
lab reports `waiting_for_data` until then rather than opening a tournament
whose ranking was fitted to an afternoon.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.compound.service import CompoundService
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.kol import ranking
from app.kol import spec as kspec
from app.lab.scheduler import DRY_RUN_LOCK_NAMESPACE
from app.models.kol import KolWalletRank
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)

#: "KOLL" — its own key in the shared dry-run namespace.
KOL_LAB_LOCK_KEY = 0x4B4F4C4C

#: Fewer ranked wallets than this and there is nothing to test: the top of a
#: list of six is not a ranking, it is the list.
MIN_RANKED_WALLETS = 10


async def freeze_ranking(session, *, now: datetime) -> int:
    """Take the ranking once, if it has not been taken. Returns rows written.

    Idempotent on `spec_version`: once a tournament's wallets exist they are
    never recomputed, because the whole claim is that THESE wallets, chosen on
    THIS date, keep hitting afterwards.
    """
    existing = int(await session.scalar(
        select(func.count()).select_from(KolWalletRank)
        .where(KolWalletRank.spec_version == kspec.SPEC_VERSION)
    ) or 0)
    if existing:
        return 0

    ranked = await ranking.rank(session, as_of=now)
    if len(ranked) < MIN_RANKED_WALLETS:
        logger.info("kol_ranking_waiting", ranked=len(ranked),
                    needed=MIN_RANKED_WALLETS)
        return 0

    scored, base = await ranking.base_rate(session, as_of=now)
    for position, w in enumerate(ranked, 1):
        session.add(KolWalletRank(
            spec_version=kspec.SPEC_VERSION, computed_at=now,
            wallet_address=w.wallet_address, rank=position,
            early_buys=w.early_buys, hits=w.hits, hit_rate=w.hit_rate,
        ))
    await session.flush()
    logger.info("kol_ranking_frozen", wallets=len(ranked), scored=scored,
                base_rate=base, top_hit_rate=ranked[0].hit_rate)
    return len(ranked)


@celery_app.task(name="app.kol.scheduler.kol_tick")
def kol_tick() -> dict[str, Any]:
    """Freeze the ranking if needed, then judge, settle and bank."""
    return run_async(_kol_tick())


async def _kol_tick() -> dict[str, Any]:
    if not settings.FEATURE_LAB_ENABLED:
        return {"skipped": "lab_disabled"}
    if not getattr(settings, "FEATURE_KOL_LAB_ENABLED", False):
        return {"skipped": "kol_disabled"}
    try:
        async with SessionFactory() as session:
            acquired = await session.scalar(
                select(func.pg_try_advisory_xact_lock(
                    DRY_RUN_LOCK_NAMESPACE, KOL_LAB_LOCK_KEY
                ))
            )
            if not acquired:
                await session.rollback()
                return {"skipped": "kol_already_running"}

            now = datetime.now(UTC)
            frozen = await freeze_ranking(session, now=now)

            # No ranking, no tournament. Opening one now would freeze
            # `valid_from` — which can never move — against wallets chosen
            # from too little data, and the experiment would be spent.
            ranked_total = int(await session.scalar(
                select(func.count()).select_from(KolWalletRank)
                .where(KolWalletRank.spec_version == kspec.SPEC_VERSION)
            ) or 0)
            if ranked_total < MIN_RANKED_WALLETS:
                await session.commit()
                return {"skipped": "waiting_for_data", "ranked": ranked_total}

            outcome = await CompoundService(session, registry=kspec).tick(now=now)
            await session.commit()
    except Exception:
        logger.exception("kol_tick_failed")
        return {"failed": True}
    if frozen:
        outcome["ranking_frozen"] = frozen
    return outcome
