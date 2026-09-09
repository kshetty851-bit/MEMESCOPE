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

from app.core.logging import get_logger
from app.models.market import TokenMarketSnapshot
from app.models.radar import RadarToken
from app.security.service import capture_candidate_security

logger = get_logger(__name__)

#: How far back to look, ON THE CLOCK THE LABS ACTUALLY JUDGE BY.
#:
#: That clock is `RadarToken.first_detected_at`, not `DiscoveredToken
#: .discovered_at`, and getting this wrong twice in one day cost every
#: evaluation the labs needed:
#:
#: * Bounding `captured_at` alone — "has a recent deep print" — selects coins
#:   discovered yesterday and still trading. Measured: 67 candidates averaging
#:   4.6 HOURS old, reaching 30 hours, fed oldest-first into a cap of 25. The
#:   cap was spent on coins judged hours earlier. 158 of 168 lab entries were
#:   bought with no evaluation on disk.
#: * Bounding `discovered_at` instead looked right and was worse: the labs
#:   judge at radar admission + 10 minutes, and radar admits a coin 60-76
#:   MINUTES after discovery. So that window held coins an hour too YOUNG to
#:   be judged, and MOV-03 declined eight consecutive candidates with zero
#:   evaluations on disk at their checkpoint.
#:
#: On the radar clock the population is small and entirely relevant: 4 admitted
#: in 20 minutes, all four already deep, ~24 an hour. Far inside the cap, so it
#: stops binding and oldest-first genuinely means nearest-its-checkpoint-first.
LOOKBACK = timedelta(minutes=20)

#: Only coins deep enough for a lab to buy. Matches the labs' own floor:
#: evaluating what nothing can trade would spend the RPC budget on noise.
MIN_LIQUIDITY_USD = 100_000


async def candidates(session: AsyncSession, *, now: datetime) -> list[str]:
    """Newly RADAR-ADMITTED mints deep enough for a lab to buy.

    Keyed on `RadarToken.first_detected_at` because that is what the engine
    keys on: `_due_candidates` selects radar rows and sets `checkpoint_at =
    first_detected_at + checkpoint_minutes`. Evidence gathered on any other
    clock arrives for the wrong coins — see `LOOKBACK`.

    Ordered oldest first, which on this clock genuinely means nearest its
    checkpoint: admission + 10 minutes is the moment being prepared for, so the
    cap is spent on the coins about to be judged.

    Still bounded by `captured_at` as well, so a coin must be currently deep
    rather than merely admitted at some point — evaluating what nothing can
    trade would spend the RPC budget on noise.
    """
    rows = await session.execute(
        select(RadarToken.mint_address, RadarToken.first_detected_at)
        .join(TokenMarketSnapshot,
              TokenMarketSnapshot.mint_address == RadarToken.mint_address)
        .where(RadarToken.first_detected_at >= now - LOOKBACK,
               TokenMarketSnapshot.captured_at >= now - LOOKBACK,
               TokenMarketSnapshot.liquidity_usd >= MIN_LIQUIDITY_USD)
        .distinct()
    )
    seen = sorted({(r.first_detected_at, r.mint_address) for r in rows})
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

