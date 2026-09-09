"""Security evidence for the coins the LABS are about to judge.

The platform has had a security evaluator for a long time — contract checks,
mint authority, freeze authority, liquidity verification — and the Paper
Wallet has always been gated on it. The labs were not, and nothing evaluated
the coins they trade: of the fifty tokens the Movers Lab closed on
2026-09-09, ZERO had an evaluation at the moment it was bought. The evaluator
was busy on a different population entirely.

That mattered because of what those fifty trades looked like. Partial losses
averaged fourteen cents. The entire loss — five trades, -$76 against +$113
from everything else — was coins going to ZERO, and no exit rule reaches a
coin that rugs inside its holding period. Rug risk was the only lever left,
and the tool for it was already built and simply not pointed here.

## Why this is a separate pass and not a feature lookup

Evaluating inside the decision would put an RPC round trip in the lab's hot
path, and a rule that is slow is a rule that misses its checkpoint. So
evidence is gathered AHEAD of the checkpoint instead: labs judge a coin ten
minutes after it is first seen, this runs every minute over coins seen in the
last few, and by the time a checkpoint arrives the verdict is already on
disk.

A coin evaluated too late is simply not gated — see the feature in
`lab/service.py`. That is the honest failure: "we could not look" is recorded
as absence rather than as a pass, and an arm that requires a verdict declines
rather than guesses.

## Bounded, because it shares a worker with enrichment

`evaluate_candidates` caps each pass at `TOKEN_SECURITY_MAX_PER_PASS` and
reuses anything still fresh, so most passes make no RPC call at all. This adds
a query and, at most, that cap — it cannot fan out further however many coins
launch.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.market import TokenMarketSnapshot
from app.models.token import DiscoveredToken
from app.security.service import capture_candidate_security

logger = get_logger(__name__)

#: How far back to look for coins worth evaluating. Wide enough to cover a
#: ten-minute checkpoint with room for a late tick, narrow enough that the
#: pass does not keep re-offering the same stale population.
#:
#: APPLIED TO AGE, NOT TO SNAPSHOT RECENCY, and that distinction was the whole
#: bug. Bounding `captured_at` alone selects "coins with a recent deep print",
#: which on 2026-09-09 was 67 mints averaging 4.6 HOURS old and reaching 30
#: hours — a coin discovered yesterday and still trading has a print from a
#: minute ago. Ordered oldest-first, the 25-per-pass cap was spent entirely on
#: coins judged hours earlier and never reached one approaching its checkpoint.
#: 158 of 168 lab entries were bought with no evaluation on disk because of it.
#:
#: Bounded by `discovered_at` as well, the population is what the docstring
#: always claimed: ~6 live candidates, ~9.3 per 20 minutes in steady state,
#: comfortably inside the cap — so the cap stops binding and oldest-first
#: genuinely means closest-to-its-checkpoint-first.
LOOKBACK = timedelta(minutes=20)

#: Only coins deep enough for a lab to buy. Matches the labs' own floor:
#: evaluating what nothing can trade would spend the RPC budget on noise.
MIN_LIQUIDITY_USD = 100_000


async def candidates(session: AsyncSession, *, now: datetime) -> list[str]:
    """Recently-seen pump.fun mints deep enough for a lab to buy.

    Ordered oldest first, so a coin approaching its checkpoint is evaluated
    before one that has only just appeared — the cap should be spent on the
    coins about to be judged, not on the newest arrivals.

    Both bounds are on `LOOKBACK`: the snapshot must be recent (the coin is
    still trading and still deep) AND the coin must itself be young (it has not
    already been judged). Dropping the second turns "oldest first" into "coins
    discovered furthest in the past first", which is the opposite of the
    intent — see the constant.
    """
    programs = list(settings.SCANNER_WATCH_PROGRAMS)
    rows = await session.execute(
        select(TokenMarketSnapshot.mint_address,
               DiscoveredToken.discovered_at)
        .join(DiscoveredToken,
              DiscoveredToken.mint_address == TokenMarketSnapshot.mint_address)
        .where(TokenMarketSnapshot.captured_at >= now - LOOKBACK,
               DiscoveredToken.discovered_at >= now - LOOKBACK,
               TokenMarketSnapshot.liquidity_usd >= MIN_LIQUIDITY_USD,
               DiscoveredToken.source_program.in_(programs))
        .distinct()
    )
    seen = sorted({(r.discovered_at, r.mint_address) for r in rows})
    return [mint for _at, mint in seen]


async def cover_lab_candidates(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Evaluate what the labs are about to judge. Returns mints offered.

    Best-effort by construction: `capture_candidate_security` swallows its own
    failures on the principle that observation must never change a trading
    decision. A security audit that stopped the labs it audits would be the
    loudest possible way to fail.
    """
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    mints = await candidates(session, now=moment)
    if not mints:
        return 0
    await capture_candidate_security(session, mints, now=moment)
    return len(mints)

