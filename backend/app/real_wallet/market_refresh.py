"""A current market reading for a token the wallet is about to buy.

The safety gate refuses a buy without a market snapshot younger than
`REAL_WALLET_SAFETY_MAX_MARKET_AGE_SECONDS`, and it is right to: its price and
liquidity checks are all made against that reading. But enrichment reaches a
new token on its own schedule. For the graduation arm the platform's first
snapshot landed a median 82 seconds after the lab decided — past the decision's
own 60-second life — so 181 of 233 of its trades would have been refused for
having no reading at all, not for anything wrong with the token.

This asks for the reading when the wallet needs it, through the platform's own
enrichment path: the same provider, the same sanity firewall, the same suspect
marking as every other snapshot. It decides nothing. The gate still applies
every rule it applied before, to whatever reading this leaves behind — a
suspect print is still refused, a failed fetch still leaves the gate without
data, and both still end in REJECT.

When the provider has not listed the pool yet, the graduation lab's own live
DexScreener poll of it is used instead, written by that same path and marked
`LAB_PROVIDER`. See `_lab_reading`.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.labs.graduation.models import GradPostgradSample
from app.models.market import LANE_NURSERY, TradingStatus
from app.repositories.market import MarketSnapshotRepository
from app.repositories.token import TokenRepository
from app.services.market.providers.base import MarketData, MarketDataProvider
from app.services.market.providers.dexscreener import MIN_TRADEABLE_LIQUIDITY_USD
from app.services.market.providers.registry import get_provider
from app.services.market.service import FetchedBatch, MarketEnrichmentService

logger = get_logger(__name__)

#: A reading younger than this is used as it is. Well inside the gate's 90s, so
#: the gate never judges a price older than the move it is about to buy into.
FRESH_S = 20

#: The `provider` a snapshot taken from the graduation lab's poll carries, so a
#: reading is never mistaken for one the platform's own provider made.
LAB_PROVIDER = "dexscreener:grad_lab"


class Reading(NamedTuple):
    """What was done, and when the reading the gate will see was taken."""

    status: str
    captured_at: datetime | None = None


async def ensure_fresh(
    session: AsyncSession,
    mint: str,
    *,
    now: datetime,
    provider: MarketDataProvider | None = None,
) -> Reading:
    """Make sure `mint` has a current snapshot.

    Never raises: a reading that cannot be had is the gate's to refuse.

    The caller must judge the reading no earlier than `captured_at`. A fetch
    finishes after `now`, and the gate reads a snapshot from its future as
    stale — which would refuse exactly the reading this exists to supply.
    """
    snapshots = MarketSnapshotRepository(session)
    latest = await snapshots.latest_for_mint(mint)
    if latest is not None and (now - latest.captured_at).total_seconds() <= FRESH_S:
        return Reading("fresh", latest.captured_at)
    token = await TokenRepository(session).get_by_mint(mint)
    if token is None:
        return Reading("token_unknown")

    owned = provider is None
    provider = provider or get_provider()
    try:
        if owned:
            await provider.start()
        service = MarketEnrichmentService(session, provider)
        state = await service.states.get_by_mint(mint)
        if state is None:
            await service.states.ensure_state(
                token_id=token.id, mint_address=mint, next_refresh_at=now,
                priority=LANE_NURSERY)
            state = await service.states.get_by_mint(mint)
        if state is None:
            return Reading("no_enrichment_state")
        fetched = await service.fetch([mint])
        listed = fetched.results.get(mint)
        from_lab = False
        if listed is None or not listed.has_market:
            lab = await _lab_reading(session, mint, now=now)
            if lab is not None:
                fetched = FetchedBatch(results={mint: lab}, error=None, degraded=False,
                                       unavailable=False, retry_after_seconds=None,
                                       latency_ms=0)
                from_lab = True
        # Written by the same path either way: the same row, the same firewall.
        await service.enrich([state], fetched=fetched)
    except Exception as exc:  # the gate refuses what this could not fetch
        logger.warning("real_wallet_market_refresh_failed", mint=mint,
                       error=str(exc)[:120])
        return Reading("failed")
    finally:
        if owned:
            await provider.close()
    # Read back through the gate's own lens: a print the firewall marked
    # suspect is not a reading, whatever was written.
    after = await snapshots.latest_for_mint(mint)
    if after is None or (latest is not None and after.id == latest.id):
        return Reading("no_reading")
    return Reading("refreshed_from_lab" if from_lab else "refreshed", after.captured_at)


async def _lab_reading(
    session: AsyncSession, mint: str, *, now: datetime
) -> MarketData | None:
    """The graduation lab's own live DexScreener poll of this pool, if current.

    The lab polls `/tokens/v1` for every graduation and opens its paper trade
    on that poll; the platform's provider asks `/latest/dex/tokens`, which
    lists a pool this new later. On all 11 buys refused MARKET_DATA_MISSING
    between 2026-09-17 19:35 and 2026-09-18 03:00 the lab held a reading 0-6s
    old, and the platform's first came 181-184s later on its no-data retry -
    the wallet was refusing the very pool its paper book had just bought.

    Only a live poll with a price and a depth, and no older than a reading
    this module would reuse anyway. It decides nothing: the gate applies every
    rule to it that it applies to any other snapshot.
    """
    row = await session.scalar(
        select(GradPostgradSample)
        .where(GradPostgradSample.mint == mint,
               # A live poll; `geckoterminal` rows are candles backfilled later.
               GradPostgradSample.source == "dexscreener",
               GradPostgradSample.price_usd.is_not(None),
               GradPostgradSample.liquidity_usd.is_not(None),
               GradPostgradSample.ts >= now - timedelta(seconds=FRESH_S))
        .order_by(GradPostgradSample.ts.desc())
        .limit(1)
    )
    if row is None or row.liquidity_usd is None:
        return None
    # DexScreener's own rule, `DexScreenerProvider._to_market_data`, applied
    # to the same fields.
    if not row.pair_address:
        status = TradingStatus.UNKNOWN
    elif row.liquidity_usd >= MIN_TRADEABLE_LIQUIDITY_USD:
        status = TradingStatus.TRADING
    else:
        status = TradingStatus.INACTIVE
    return MarketData(
        mint_address=mint, price_usd=row.price_usd, price_native=row.price_native,
        liquidity_usd=row.liquidity_usd, fully_diluted_valuation=row.fdv,
        volume_1h=row.volume_h1_usd, volume_5m=row.volume_m5_usd,
        dex_name=row.dex_id, pool_address=row.pair_address, trading_status=status,
        provider=LAB_PROVIDER, observed_at=row.ts,
    )
