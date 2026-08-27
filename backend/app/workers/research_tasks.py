"""V4 Phase 2 research-data collectors. Instrumentation, never strategy.

Four small beats behind one flag (`FEATURE_RESEARCH_COLLECTORS_ENABLED`), plus
the nursery expiry sweep. Every task is bounded per run, best-effort per item,
and reports what it did — a collector that fails must cost nothing but its own
data point, and a collector that silently caps its coverage is worse than one
that says so.

None of these results is consumed by any trading path. The tables they fill
exist so the NEXT research round has what THIS one did not: execution truth
for skipped candidates, holder concentration, a point-in-time universe, and
regime telemetry that separates the pipeline from the market.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.models.market import EnrichmentStatus, TokenEnrichmentState
from app.models.radar import RadarToken
from app.models.research_data import (
    HolderSnapshot,
    JupiterUniverseSnapshot,
    NurseryAdmission,
    RegimeSnapshot,
    ResearchQuote,
)
from app.models.token import DiscoveredToken
from app.radar import nursery
from app.repositories.market import MarketSnapshotRepository
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)

USDC_DECIMALS = 6
#: V5 protocol §4 decision checkpoints, minutes after nursery entry. Frozen.
CHECKPOINT_MINUTES: tuple[int, ...] = (5, 10, 20, 30, 45, 60)
#: How late a checkpoint quote may still be taken and still count as that
#: checkpoint. Beyond this the moment is gone and is recorded as missing.
CHECKPOINT_GRACE_MINUTES = 4
#: pump.fun mints are uniformly 6 decimals; used only when the token row has
#: no stored value, and recorded implicitly by the raw amounts either way.
DEFAULT_DECIMALS = 6


# --------------------------------------------------------------------- nursery

@celery_app.task(name="app.workers.research_tasks.nursery_sweep")
def nursery_sweep() -> dict[str, Any]:
    """Close OBSERVING rows that were never re-judged past their window."""
    return run_async(_nursery_sweep())


async def _nursery_sweep() -> dict[str, Any]:
    if settings.RADAR_MIN_OBSERVATION_MINUTES <= 0:
        return {"skipped": "nursery_disabled"}
    async with SessionFactory() as session:
        expired = await nursery.expire_stale(session)
        await session.commit()
    return {"expired": expired}


# --------------------------------------------------------- skipped-quote truth

@celery_app.task(name="app.workers.research_tasks.research_quotes_sample")
def research_quotes_sample() -> dict[str, Any]:
    """Round-trip router quotes for candidates the wallets did NOT trade."""
    return run_async(_research_quotes_sample())


async def _research_quotes_sample() -> dict[str, Any]:
    if not settings.FEATURE_RESEARCH_COLLECTORS_ENABLED:
        return {"skipped": "collectors_disabled"}

    from app.services.jupiter import JupiterExecutionClient

    batch = settings.RESEARCH_QUOTE_BATCH
    size = Decimal(str(settings.RESEARCH_QUOTE_SIZE_USD))
    now = datetime.now(UTC)
    quoted = failures = 0

    async with SessionFactory() as session:
        # --- checkpoint-aligned candidates first (V5 protocol §4) ------------
        # A nursery member that has just crossed one of the fixed decision
        # checkpoints and has no quote for it yet. This is the only quote that
        # can answer "was this token two-sided AT the decision moment" — a
        # randomly timed sample cannot, however many of them there are.
        rows: list[Any] = []
        checkpoints: dict[str, int] = {}
        for minutes in CHECKPOINT_MINUTES:
            if len(rows) >= batch:
                break
            due = (
                select(NurseryAdmission.mint_address, NurseryAdmission.token_id)
                .where(
                    NurseryAdmission.status == "observing",
                    NurseryAdmission.entered_at <= now - timedelta(minutes=minutes),
                    # inside a grace window, so a late beat still lands the
                    # checkpoint rather than skipping it forever
                    NurseryAdmission.entered_at
                    > now - timedelta(minutes=minutes + CHECKPOINT_GRACE_MINUTES),
                    ~select(ResearchQuote.id)
                    .where(
                        ResearchQuote.mint_address == NurseryAdmission.mint_address,
                        ResearchQuote.checkpoint_minutes == minutes,
                    )
                    .exists(),
                )
                .order_by(NurseryAdmission.entered_at)
                .limit(batch - len(rows))
            )
            for mint, token_id in (await session.execute(due)).all():
                if mint in checkpoints:
                    continue
                checkpoints[mint] = minutes
                rows.append((mint, token_id))

        # Candidates: newest admissions and observing nursery members that have
        # no quote in the last hour. Newest first — execution truth is most
        # valuable at the moment research would have acted.
        recent_quote = (
            select(ResearchQuote.mint_address)
            .where(ResearchQuote.requested_at >= now - timedelta(hours=1))
            .scalar_subquery()
        )
        admitted = (
            select(RadarToken.mint_address, RadarToken.token_id)
            .where(
                RadarToken.first_detected_at >= now - timedelta(hours=6),
                RadarToken.mint_address.not_in(recent_quote),
            )
            .order_by(RadarToken.first_detected_at.desc())
            .limit(batch)
        )
        if len(rows) < batch:
            rows += list((await session.execute(admitted.limit(batch - len(rows)))).all())
        if len(rows) < batch:
            observing = (
                select(NurseryAdmission.mint_address, NurseryAdmission.token_id)
                .where(
                    NurseryAdmission.status == "observing",
                    NurseryAdmission.mint_address.not_in(recent_quote),
                )
                .order_by(NurseryAdmission.entered_at.desc())
                .limit(batch - len(rows))
            )
            rows += list((await session.execute(observing)).all())
        if not rows:
            return {"quoted": 0, "candidates": 0}

        mints = [r[0] for r in rows]
        decimals_rows = await session.execute(
            select(DiscoveredToken.mint_address, DiscoveredToken.decimals).where(
                DiscoveredToken.mint_address.in_(mints)
            )
        )
        decimals = {m: d for m, d in decimals_rows.all()}
        snapshots = await MarketSnapshotRepository(session).latest_for_mints(mints)

        client = JupiterExecutionClient()
        try:
            for mint, token_id in rows:
                snap = snapshots.get(mint)
                price = snap.price_usd if snap is not None else None
                liq = snap.liquidity_usd if snap is not None else None
                dec = decimals.get(mint) or DEFAULT_DECIMALS
                record = dict(
                    mint_address=mint,
                    token_id=token_id,
                    requested_at=datetime.now(UTC),
                    size_usd=size,
                    price_usd_at=price,
                    liquidity_usd_at=liq,
                    context=("checkpoint" if mint in checkpoints else "skip_sample"),
                    checkpoint_minutes=checkpoints.get(mint),
                )
                try:
                    buy = await client.buy_quote(
                        output_mint=mint, input_usd=size, output_decimals=dec, now=now
                    )
                    session.add(ResearchQuote(
                        **record, side="buy", ok=True,
                        in_amount_raw=Decimal(buy.input_amount_raw),
                        out_amount_raw=Decimal(buy.output_amount_raw),
                        price_impact_pct=buy.price_impact_pct,
                        route=buy.route[:255],
                    ))
                    quoted += 1
                    # Round trip: can what was just bought be sold again?
                    try:
                        sell = await client.sell_quote(
                            input_mint=mint,
                            quantity=buy.output_amount,
                            input_decimals=dec,
                            now=now,
                        )
                        session.add(ResearchQuote(
                            **record, side="sell", ok=True,
                            in_amount_raw=Decimal(sell.input_amount_raw),
                            out_amount_raw=Decimal(sell.output_amount_raw),
                            price_impact_pct=sell.price_impact_pct,
                            route=sell.route[:255],
                        ))
                        quoted += 1
                    except Exception as exc:  # sell side refused: the finding itself
                        session.add(ResearchQuote(
                            **record, side="sell", ok=False,
                            failure_reason=type(exc).__name__[:64],
                        ))
                        failures += 1
                except Exception as exc:
                    session.add(ResearchQuote(
                        **record, side="buy", ok=False,
                        failure_reason=type(exc).__name__[:64],
                    ))
                    failures += 1
        finally:
            close = getattr(client, "close", None)
            if close is not None:
                try:
                    await close()
                except Exception:  # pragma: no cover - best effort
                    pass
        await session.commit()

    logger.info("research_quotes_sampled", quoted=quoted, failures=failures)
    return {"quoted": quoted, "failures": failures}


# ------------------------------------------------------------- holder snapshots

@celery_app.task(name="app.workers.research_tasks.holder_snapshots_collect")
def holder_snapshots_collect() -> dict[str, Any]:
    """Top-holder concentration for nursery members and fresh admissions."""
    return run_async(_holder_snapshots_collect())


def _pct(amount: int, supply: int) -> Decimal | None:
    if supply <= 0:
        return None
    return (Decimal(amount) / Decimal(supply) * 100).quantize(Decimal("0.0001"))


async def _holder_snapshots_collect() -> dict[str, Any]:
    if not settings.FEATURE_RESEARCH_COLLECTORS_ENABLED:
        return {"skipped": "collectors_disabled"}

    from app.services.rpc.registry import get_research_rpc

    batch = settings.HOLDER_SNAPSHOT_BATCH
    now = datetime.now(UTC)
    written = failures = 0

    async with SessionFactory() as session:
        # Lifecycle moments, not a refresh loop: holder concentration is a
        # research fact about a MOMENT (what did distribution look like when
        # the token entered observation? when it was admitted?), and refetching
        # an unchanged answer burns quota without adding a datum. One snapshot
        # per (mint, context), enforced by NOT EXISTS — so a failed attempt is
        # retried on later beats until a real row (success or terminal failure
        # with reason) exists for that moment.
        def _lacking(context: str):
            return ~select(HolderSnapshot.id).where(
                HolderSnapshot.mint_address == NurseryAdmission.mint_address
                if context == "nursery_entry"
                else HolderSnapshot.mint_address == RadarToken.mint_address,
                HolderSnapshot.context == context,
                HolderSnapshot.failure_reason.is_(None),
                # a recent failed attempt also defers the retry a little
            ).exists()

        recent_attempt = (
            select(HolderSnapshot.mint_address)
            .where(HolderSnapshot.captured_at >= now - timedelta(minutes=30))
            .scalar_subquery()
        )
        candidates = (
            select(
                NurseryAdmission.mint_address,
                NurseryAdmission.token_id,
                func.coalesce(NurseryAdmission.status, "observing").label("ctx"),
            )
            .where(
                NurseryAdmission.status == "observing",
                _lacking("nursery_entry"),
                NurseryAdmission.mint_address.not_in(recent_attempt),
            )
            .order_by(NurseryAdmission.entered_at.desc())
            .limit(batch)
        )
        rows = list((await session.execute(candidates)).all())
        if len(rows) < batch:
            admitted = (
                select(
                    RadarToken.mint_address,
                    RadarToken.token_id,
                    func.coalesce(RadarToken.category, "admission").label("ctx"),
                )
                .where(
                    RadarToken.first_detected_at >= now - timedelta(hours=24),
                    _lacking("admission"),
                    RadarToken.mint_address.not_in(recent_attempt),
                )
                .order_by(RadarToken.first_detected_at.desc())
                .limit(batch - len(rows))
            )
            rows += list((await session.execute(admitted)).all())
        if not rows:
            return {"written": 0}

        mints = [r[0] for r in rows]
        snapshots = await MarketSnapshotRepository(session).latest_for_mints(mints)
        creators = dict(
            (await session.execute(
                select(DiscoveredToken.mint_address, DiscoveredToken.creator_address)
                .where(DiscoveredToken.mint_address.in_(mints))
            )).all()
        )

        # `getTokenLargestAccounts` is aggressively rate-limited on the public
        # endpoint (measured live: every call 429'd, 30 failure rows, 0 data).
        # Use the keyed vendor node when one is configured, and pace the calls
        # regardless — this is a background collector, not a hot path.
        async with get_research_rpc() as rpc:
            for mint, token_id, ctx in rows:
                # This method is rate-limited harder than the general RPS on
                # both the public node AND Helius (measured live: 0.6s pacing
                # still 429'd 14/15). The collector's budget is minutes, not
                # seconds — 2.5s a token clears a batch well inside one beat.
                await asyncio.sleep(2.5)
                context = "nursery_entry" if ctx == "observing" else "admission"
                try:
                    largest = await rpc.call("getTokenLargestAccounts", [mint])
                    supply_resp = await rpc.call("getTokenSupply", [mint])
                    accounts = [
                        {"address": a["address"], "amount": int(a["amount"])}
                        for a in largest["value"]
                    ]
                    supply = int(supply_resp["value"]["amount"])
                    decimals = int(supply_resp["value"].get("decimals", 0))

                    snap = snapshots.get(mint)
                    pool = snap.pool_address if snap is not None else None
                    creator = creators.get(mint)
                    excluded = [
                        {"address": a["address"], "reason": "pool", "amount": a["amount"]}
                        for a in accounts
                        if pool and a["address"] == pool
                    ]
                    economic = [a for a in accounts if not (pool and a["address"] == pool)]
                    amounts = sorted((a["amount"] for a in economic), reverse=True)
                    creator_amount = next(
                        (a["amount"] for a in economic if creator and a["address"] == creator),
                        None,
                    )
                    session.add(HolderSnapshot(
                        token_id=token_id,
                        mint_address=mint,
                        captured_at=datetime.now(UTC),
                        provider=getattr(rpc, "last_provider", None) or rpc.name,
                        rpc_latency_ms=getattr(rpc, "last_latency_ms", None),
                        rpc_fallback_used=getattr(rpc, "last_fallback_used", None),
                        context=context,
                        supply_raw=Decimal(supply),
                        decimals=decimals,
                        top1_pct=_pct(sum(amounts[:1]), supply),
                        top5_pct=_pct(sum(amounts[:5]), supply),
                        top10_pct=_pct(sum(amounts[:10]), supply),
                        creator_pct=(_pct(creator_amount, supply) if creator_amount else None),
                        largest_nonpool_pct=_pct(amounts[0], supply) if amounts else None,
                        accounts={"top": accounts},
                        excluded={"entries": excluded} if excluded else None,
                    ))
                    written += 1
                except Exception as exc:
                    session.add(HolderSnapshot(
                        token_id=token_id,
                        mint_address=mint,
                        captured_at=datetime.now(UTC),
                        provider=getattr(rpc, "last_provider", None) or rpc.name,
                        rpc_latency_ms=None,
                        rpc_fallback_used=None,
                        context=context,
                        failure_reason=type(exc).__name__[:64],
                    ))
                    failures += 1
        await session.commit()

    logger.info("holder_snapshots_collected", written=written, failures=failures)
    return {"written": written, "failures": failures}


# --------------------------------------------------------------- universe daily

@celery_app.task(name="app.workers.research_tasks.universe_snapshot_daily")
def universe_snapshot_daily() -> dict[str, Any]:
    """Point-in-time capture of Jupiter's verified list. One request a day."""
    return run_async(_universe_snapshot_daily())


async def _universe_snapshot_daily() -> dict[str, Any]:
    if not settings.FEATURE_RESEARCH_COLLECTORS_ENABLED:
        return {"skipped": "collectors_disabled"}

    import httpx
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    now = datetime.now(UTC)
    url = "https://lite-api.jup.ag/tokens/v2/tag?query=verified"
    # The endpoint 403s a default client UA (measured in V2); a browser-shaped
    # one is required. Identified as research per the platform's honesty rule.
    headers = {"accept": "application/json", "User-Agent": "Mozilla/5.0 (MEMESCOPE research)"}
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        tokens = response.json()

    rows = []
    for t in tokens:
        mint = t.get("id") or t.get("address") or t.get("mint")
        if not mint:
            continue
        created_raw = (t.get("firstPool") or {}).get("createdAt") or t.get("createdAt")
        created = None
        if isinstance(created_raw, str):
            try:
                created = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
            except ValueError:
                created = None
        rows.append(dict(
            snapshot_date=now.date(),
            mint_address=mint,
            fetched_at=now,
            symbol=(t.get("symbol") or "")[:32] or None,
            provider_created_at=created,
            liquidity_usd=t.get("liquidity"),
            market_cap=t.get("mcap") or t.get("marketCap"),
            holder_count=t.get("holderCount"),
            organic_score=t.get("organicScore"),
        ))
    if not rows:
        return {"written": 0}

    async with SessionFactory() as session:
        stmt = pg_insert(JupiterUniverseSnapshot).values(rows).on_conflict_do_nothing(
            index_elements=[
                JupiterUniverseSnapshot.snapshot_date,
                JupiterUniverseSnapshot.mint_address,
            ]
        )
        await session.execute(stmt)
        await session.commit()
    logger.info("universe_snapshot_written", tokens=len(rows))
    return {"written": len(rows)}


# ------------------------------------------------------------ universe enrolment

@celery_app.task(name="app.workers.research_tasks.universe_enrol")
def universe_enrol() -> dict[str, Any]:
    """Register qualifying market tokens so the pipeline can price them.

    Runs after the daily snapshot, and again through the day: the snapshot is
    what Jupiter said, this is what the platform is willing to observe, and a
    token that crosses the liquidity floor between snapshots should not wait a
    day to be seen.
    """
    return run_async(_universe_enrol())


async def _universe_enrol() -> dict[str, Any]:
    from app.universe.enrolment import enrol

    async with SessionFactory() as session:
        result = await enrol(session)
        await session.commit()
    return result


# ------------------------------------------------------------- regime telemetry

@celery_app.task(name="app.workers.research_tasks.regime_snapshot_hourly")
def regime_snapshot_hourly() -> dict[str, Any]:
    """Two rows an hour: what the PIPELINE is doing, and what the MARKET is."""
    return run_async(_regime_snapshot_hourly())


async def _regime_snapshot_hourly() -> dict[str, Any]:
    if not settings.FEATURE_RESEARCH_COLLECTORS_ENABLED:
        return {"skipped": "collectors_disabled"}

    now = datetime.now(UTC)
    async with SessionFactory() as session:
        population = await _population_payload(session, now)
        market = await _market_payload(session, now)
        session.add(RegimeSnapshot(captured_at=now, kind="population", payload=population))
        session.add(RegimeSnapshot(captured_at=now, kind="market", payload=market))
        await session.commit()
    return {"population": population.get("admissions_24h"), "market": market.get("sol_usd")}


async def _population_payload(session: Any, now: datetime) -> dict[str, Any]:
    day_ago, hour_ago = now - timedelta(hours=24), now - timedelta(hours=1)
    admissions_24h = await session.scalar(
        select(func.count()).select_from(RadarToken).where(RadarToken.first_detected_at >= day_ago)
    )
    admissions_1h = await session.scalar(
        select(func.count()).select_from(RadarToken).where(RadarToken.first_detected_at >= hour_ago)
    )
    median_age_min = await session.scalar(text(
        """
        SELECT percentile_cont(0.5) WITHIN GROUP (
            ORDER BY EXTRACT(EPOCH FROM (r.first_detected_at - d.discovered_at)) / 60.0)
        FROM radar_tokens r JOIN discovered_tokens d ON d.id = r.token_id
        WHERE r.first_detected_at >= :day_ago
        """
    ).bindparams(day_ago=day_ago))
    discoveries_1h = await session.scalar(
        select(func.count()).select_from(DiscoveredToken).where(DiscoveredToken.discovered_at >= hour_ago)
    )
    nursery_counts = dict(
        (await session.execute(
            select(NurseryAdmission.status, func.count()).group_by(NurseryAdmission.status)
        )).all()
    )
    overdue = dict(
        (await session.execute(
            select(TokenEnrichmentState.priority, func.count())
            .where(
                TokenEnrichmentState.status == EnrichmentStatus.ACTIVE,
                TokenEnrichmentState.next_refresh_at < now,
            )
            .group_by(TokenEnrichmentState.priority)
        )).all()
    )
    # The containment rule, evaluated and RECORDED — an operational statement,
    # explicitly not a validated alpha model (V4 Phase 2 §8).
    hostile = bool(
        (admissions_24h or 0) > settings.REGIME_HOSTILE_ADMISSIONS_PER_DAY
        or (median_age_min is not None and median_age_min < settings.REGIME_HOSTILE_MEDIAN_AGE_MINUTES)
    )
    return {
        "admissions_24h": int(admissions_24h or 0),
        "admissions_1h": int(admissions_1h or 0),
        "median_admitted_age_min": float(median_age_min) if median_age_min is not None else None,
        "discoveries_1h": int(discoveries_1h or 0),
        "nursery": {k: int(v) for k, v in nursery_counts.items()},
        "enrichment_overdue_by_lane": {str(k): int(v) for k, v in overdue.items()},
        "containment_hostile": hostile,
        "containment_rule": (
            f">{settings.REGIME_HOSTILE_ADMISSIONS_PER_DAY}/day or "
            f"median age <{settings.REGIME_HOSTILE_MEDIAN_AGE_MINUTES}m (operational, not alpha)"
        ),
    }


async def _market_payload(session: Any, now: datetime) -> dict[str, Any]:
    hour_ago = now - timedelta(hours=1)
    sol_usd: float | None = None
    try:
        from app.services.jupiter import JupiterExecutionClient

        client = JupiterExecutionClient()
        try:
            quote = await client.buy_quote(
                output_mint="So11111111111111111111111111111111111111112",
                input_usd=Decimal("100"),
                output_decimals=9,
                now=now,
            )
            if quote.output_amount > 0:
                sol_usd = float(Decimal("100") / quote.output_amount)
        finally:
            close = getattr(client, "close", None)
            if close is not None:
                await close()
    except Exception:
        logger.warning("regime_sol_price_unavailable")

    liq = await session.execute(text(
        """
        SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY liquidity_usd),
               count(*)
        FROM (
            SELECT DISTINCT ON (mint_address) liquidity_usd
            FROM token_market_snapshots
            WHERE captured_at >= :hour_ago
              AND suspect IS NOT TRUE
              AND liquidity_usd IS NOT NULL AND liquidity_usd > 0
            ORDER BY mint_address, captured_at DESC
        ) latest
        """
    ).bindparams(hour_ago=hour_ago))
    median_liq, active_tokens = liq.one()

    quotes = await session.execute(
        select(ResearchQuote.ok, func.count())
        .where(ResearchQuote.requested_at >= now - timedelta(hours=6))
        .group_by(ResearchQuote.ok)
    )
    by_ok = dict(quotes.all())
    ok_n, fail_n = int(by_ok.get(True, 0)), int(by_ok.get(False, 0))
    return {
        "sol_usd": sol_usd,
        "median_active_liquidity_usd": float(median_liq) if median_liq is not None else None,
        "active_priced_tokens_1h": int(active_tokens or 0),
        "route_availability_6h": (ok_n / (ok_n + fail_n)) if (ok_n + fail_n) else None,
        "quotes_sampled_6h": ok_n + fail_n,
    }


# ------------------------------------------------------- executable truth batch

@celery_app.task(name="app.workers.research_tasks.executable_outcomes_compute")
def executable_outcomes_compute(limit: int | None = None) -> dict[str, Any]:
    """Executable Track Record truth, a bounded batch at a time.

    Hourly, oldest-undecided first: with the default batch the 2,672-token
    backlog clears in about a day and the steady state is one small pass."""
    return run_async(_executable_outcomes_compute(limit))


async def _executable_outcomes_compute(limit: int | None = None) -> dict[str, Any]:
    if not settings.FEATURE_RESEARCH_COLLECTORS_ENABLED:
        return {"skipped": "collectors_disabled"}

    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.models.market import TokenMarketSnapshot, TradingStatus
    from app.models.research_data import RadarExecutableOutcome
    from app.radar import executable

    batch = limit or 200
    now = datetime.now(UTC)
    computed = skipped = 0

    async with SessionFactory() as session:
        done = select(RadarExecutableOutcome.radar_token_id).where(
            RadarExecutableOutcome.decided_24h.is_(True)
        )
        targets = list((await session.execute(
            select(RadarToken.id, RadarToken.token_id, RadarToken.first_detected_at)
            .where(RadarToken.id.not_in(done))
            .order_by(RadarToken.first_detected_at)
            .limit(batch)
        )).all())
        if not targets:
            return {"computed": 0, "remaining": 0}

        for radar_id, token_id, detected_at in targets:
            rows = (await session.execute(
                select(
                    TokenMarketSnapshot.captured_at,
                    TokenMarketSnapshot.price_usd,
                    TokenMarketSnapshot.liquidity_usd,
                    TokenMarketSnapshot.trading_status,
                    TokenMarketSnapshot.suspect,
                )
                .where(
                    TokenMarketSnapshot.token_id == token_id,
                    TokenMarketSnapshot.captured_at >= detected_at,
                    TokenMarketSnapshot.captured_at <= detected_at + timedelta(hours=73),
                )
                .order_by(TokenMarketSnapshot.captured_at)
            )).all()
            suspects = sum(1 for r in rows if r.suspect)
            readings = [
                executable.Reading(
                    captured_at=r.captured_at,
                    price_usd=r.price_usd,
                    liquidity_usd=r.liquidity_usd,
                    inactive=(r.trading_status == TradingStatus.INACTIVE),
                )
                for r in rows
                if not r.suspect
            ]
            outcome = executable.compute(
                readings, entered_at=detected_at, data_end=now
            )
            values = dict(
                radar_token_id=radar_id,
                computed_at=now,
                method_version=executable.METHOD_VERSION,
                suspects_excluded=suspects,
            )
            if outcome is None:
                # Never fillable: decided, with nothing executable about it.
                values.update(
                    executable_peak_multiple=None,
                    reached_125_24h=False,
                    reached_2x_24h=False,
                    reached_2x_72h=False,
                    final_value_frac_24h=None,
                    decided_24h=True,
                    snapshots_used=len(readings),
                )
            else:
                values.update(
                    executable_peak_multiple=outcome.executable_peak_multiple,
                    reached_125_24h=outcome.reached_125_24h,
                    reached_2x_24h=outcome.reached_2x_24h,
                    reached_2x_72h=outcome.reached_2x_72h,
                    final_value_frac_24h=outcome.final_value_frac_24h,
                    decided_24h=outcome.decided_24h,
                    snapshots_used=outcome.snapshots_used,
                )
            stmt = pg_insert(RadarExecutableOutcome).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=[RadarExecutableOutcome.radar_token_id],
                set_={k: v for k, v in values.items() if k != "radar_token_id"},
            )
            await session.execute(stmt)
            computed += 1
        await session.commit()
        remaining = int(await session.scalar(
            select(func.count()).select_from(RadarToken).where(RadarToken.id.not_in(done))
        ) or 0)

    logger.info("executable_outcomes_computed", computed=computed, remaining=remaining)
    return {"computed": computed, "skipped": skipped, "remaining": remaining}
