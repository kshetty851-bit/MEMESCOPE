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
"""

from __future__ import annotations

from datetime import datetime
from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.market import LANE_NURSERY
from app.repositories.market import MarketSnapshotRepository
from app.repositories.token import TokenRepository
from app.services.market.providers.base import MarketDataProvider
from app.services.market.providers.registry import get_provider
from app.services.market.service import MarketEnrichmentService

logger = get_logger(__name__)

#: A reading younger than this is used as it is. Well inside the gate's 90s, so
#: the gate never judges a price older than the move it is about to buy into.
FRESH_S = 20


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
        await service.enrich([state])
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
    return Reading("refreshed", after.captured_at)
