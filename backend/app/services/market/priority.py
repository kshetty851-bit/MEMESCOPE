"""Which tokens the product is actively displaying.

Sprint 28. The enrichment queue reached 36,154 active tokens, and the claim
query ordered by due time alone — so a Radar token asking for a fifteen-second
refresh sorted behind 36,000 rows that were already hours overdue. Its measured
p95 refresh gap was 106 minutes, and three of the ten rows on the homepage were
showing prices nearly three hours old.

This module decides **membership of the lane**, nothing else. It creates no
queue, no worker and no scheduler: `token_enrichment_state.priority` is one
column on the table the existing worker already drains, and `claim_due` sorts on
it before `next_refresh_at`.

Membership is *derived every cycle from what the product actually shows*, never
accumulated. A token that drops out of the Radar's visible ranks leaves the lane
on the next pass — otherwise the lane grows monotonically and becomes the
backlog it was built to escape. `ENRICHMENT_PRIORITY_MAX_TOKENS` is the second
guard on the same failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import CursorResult, func, or_, select, true, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.market import (
    LANE_DISPLAY,
    LANE_NORMAL,
    LANE_NURSERY,
    EnrichmentStatus,
    TokenEnrichmentState,
    TokenMarketSnapshot,
)
from app.models.opportunity import LIVE_STATUSES, Opportunity
from app.models.lab import LabPosition
from app.models.paper import PaperPosition
from app.models.radar import RadarToken
from app.models.research_data import NurseryAdmission
from app.models.token import DiscoveredToken
from app.paper.models import PositionStatus
from app.universe import rules as universe_rules
from app.universe.enrolment import SOURCE_PROGRAM as UNIVERSE_SOURCE_PROGRAM

#: The liquidity floor the Matrix Lab's AGED arms buy at. Polling an
#: established token nothing can trade would spend the lane on noise.
ESTABLISHED_MIN_LIQUIDITY_USD = Decimal("100000")
#: "Established" on the AGED section's own definition — the same 24 hours.
ESTABLISHED_MIN_AGE = timedelta(hours=24)
#: A token with no print at all in a day is not a market anybody is in.
ESTABLISHED_PRINT_WINDOW = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class PriorityMembership:
    """Who is in the lane, and why. Reported so the lane is auditable."""

    radar: int
    opportunities: int
    paper: int
    lab: int
    total: int
    promoted: int
    demoted: int
    capped: bool
    #: Established tokens that actually made it in — they sit last in the
    #: order, so this is the count the cap leaves rather than the count offered.
    established: int = 0

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "radar": self.radar,
            "opportunities": self.opportunities,
            "paper": self.paper,
            "lab": self.lab,
            "established": self.established,
            "total": self.total,
            "promoted": self.promoted,
            "demoted": self.demoted,
            "capped": self.capped,
        }


async def established_candidates(
    session: AsyncSession, *, now: datetime, limit: int
) -> list[str]:
    """Established markets for the Matrix Lab's AGED section to draw from.

    The section samples deep-AMM tokens at least a day old, and a sample may
    only be drawn from a token printed within two minutes (`SAMPLE_FRESHNESS`
    in `app.lab.service`). Nothing put such tokens on this lane: the
    `jupiter_verified` universe is enrolled on the normal tier, which for a
    token older than a day means one print every six hours. Measured on
    2026-09-09: 143 tokens eligible, ONE printed in the previous two hours,
    and the section drawing about one token an hour.

    Membership rotates DAILY rather than by liquidity rank: the deepest fifty
    are the majors, and a five-minute hold on a top-ten token is a different
    experiment from one on a $150k market. A hash of the mint and the date
    gives a stable subset all day and a different one tomorrow, so over a week
    the section sees the whole population rather than the same fifty coins.

    One index lookup per universe token (measured 361 ms over 181), which is
    why this reads the universe and not the snapshot table: the same question
    asked of a day of snapshots is a fifteen-second sequential scan.
    """
    if limit <= 0:
        return []
    latest = (
        select(
            TokenMarketSnapshot.liquidity_usd,
            TokenMarketSnapshot.dex_name,
            TokenMarketSnapshot.price_usd,
            TokenMarketSnapshot.suspect,
            TokenMarketSnapshot.captured_at,
        )
        .where(TokenMarketSnapshot.token_id == DiscoveredToken.id)
        .order_by(TokenMarketSnapshot.captured_at.desc())
        .limit(1)
        .lateral("latest")
    )
    # The universe wallet's own definition of "on a peg": a stablecoin held
    # five minutes returns zero with no variance and would flatter any sample.
    off_peg = [
        func.abs(latest.c.price_usd - level) / level > universe_rules.PEG_TOLERANCE
        for level in universe_rules.PEG_LEVELS
    ]
    rows = await session.scalars(
        select(DiscoveredToken.mint_address)
        .join(latest, true())
        .where(
            DiscoveredToken.source_program == UNIVERSE_SOURCE_PROGRAM,
            DiscoveredToken.block_time <= now - ESTABLISHED_MIN_AGE,
            latest.c.suspect.is_not(True),
            latest.c.dex_name.in_(universe_rules.DEEP_AMM_VENUES),
            latest.c.liquidity_usd >= ESTABLISHED_MIN_LIQUIDITY_USD,
            latest.c.liquidity_usd <= universe_rules.MAX_LIQUIDITY_USD,
            latest.c.price_usd > 0,
            *off_peg,
            latest.c.captured_at >= now - ESTABLISHED_PRINT_WINDOW,
        )
        .order_by(func.md5(DiscoveredToken.mint_address + now.strftime("%Y-%m-%d")))
        .limit(limit)
    )
    return list(rows.all())


async def resolve_membership(session: AsyncSession) -> tuple[set[str], PriorityMembership]:
    """Every mint the product is currently displaying, in three queries.

    Ordered by Radar rank so that if the cap bites it truncates the *tail* —
    the ranks nobody is looking at — rather than an arbitrary slice.
    """
    radar_mints = list(
        (
            await session.scalars(
                select(RadarToken.mint_address)
                .where(RadarToken.is_active.is_(True))
                .order_by(
                    RadarToken.current_opportunity_score.desc(),
                    RadarToken.mint_address.asc(),
                )
                .limit(settings.ENRICHMENT_PRIORITY_RADAR_RANKS)
            )
        ).all()
    )

    opportunity_mints = list(
        (
            await session.scalars(
                select(Opportunity.mint_address).where(
                    Opportunity.status.in_([status.value for status in LIVE_STATUSES])
                )
            )
        ).all()
    )

    paper_mints = list(
        (
            await session.scalars(
                select(PaperPosition.mint_address).where(
                    PaperPosition.status == PositionStatus.OPEN.value
                )
            )
        ).all()
    )

    lab_mints = list(
        (
            await session.scalars(
                select(LabPosition.mint_address).where(LabPosition.status == "open")
            )
        ).all()
    )

    # Open paper positions first. A paper holding is not merely displayed: its
    # next quote can settle an existing position, so allowing the Radar or an
    # opportunity list to consume the cap first can strand it on an old tier.
    # The lane is still one bounded, derived set; this only gives the wallet's
    # already-committed capital precedence within that set.
    #
    # LAB HOLDINGS SIT BESIDE PAPER ONES, and were missing until 2026-08-26.
    # The reasoning above is about committed capital, not about which table it
    # is recorded in — but only `paper_positions` was ever queried, so when the
    # Paper wallet was retired the lane went to `paper: 0` and the Lab's book
    # inherited no protection at all. Its tokens fell out of the refresh
    # rotation, their snapshots went stale, and 61 of 108 open positions could
    # not be marked or exited: HQ INC-056. A position the platform will not
    # re-price is a position it cannot sell.
    # ESTABLISHED TOKENS COME LAST. Nobody is looking at them; they are here
    # so a research section has a feed, and the cap must bite them before it
    # bites anything a person or a position depends on.
    established_mints = await established_candidates(
        session, now=datetime.now(UTC),
        limit=settings.ENRICHMENT_PRIORITY_ESTABLISHED_TOKENS,
    )

    ordered: list[str] = []
    seen: set[str] = set()
    for mint in [*paper_mints, *lab_mints, *radar_mints, *opportunity_mints,
                 *established_mints]:
        if mint not in seen:
            seen.add(mint)
            ordered.append(mint)

    cap = settings.ENRICHMENT_PRIORITY_MAX_TOKENS
    capped = len(ordered) > cap
    members = set(ordered[:cap])

    return members, PriorityMembership(
        radar=len(set(radar_mints)),
        opportunities=len(set(opportunity_mints)),
        paper=len(set(paper_mints)),
        lab=len(set(lab_mints)),
        total=len(members),
        promoted=0,
        demoted=0,
        capped=capped,
        established=len(set(established_mints) & members),
    )


async def apply_membership(
    session: AsyncSession, members: set[str], *, now: datetime
) -> tuple[int, int]:
    """Move rows into and out of the lane. Returns `(promoted, demoted)`.

    Two statements, both no-ops when membership has not changed — the `priority`
    predicate means an unchanged cycle writes nothing and produces no dead
    tuples for autovacuum.

    Promotion **clamps** `next_refresh_at` to at most one priority interval
    away. Sorting ahead of the backlog is not enough on its own: the stale
    tokens are stale precisely because they sit on the OLD tier's six-hour
    interval, so a promotion that left the due time alone would keep them stale
    for up to six more hours. Measured: with sort-order-only promotion, the
    tracked stale count fell just 84 -> 74 over four minutes.

    Clamping cannot monopolise a claim window — the lane is capped at
    `ENRICHMENT_PRIORITY_MAX_TOKENS` (200), while the worker claims
    `ENRICHMENT_BATCH_LIMIT` (60) every `ENRICHMENT_POLL_INTERVAL_SECONDS` (5),
    which is 720 claims a minute. The lane is a fraction of one minute's
    capacity.

    It is a **clamp, not an assignment**: a token already due sooner keeps its
    earlier time, so promotion can only ever bring a refresh forward.
    """
    promoted = 0
    demoted = 0
    clamp_to = now + timedelta(seconds=settings.ENRICHMENT_PRIORITY_INTERVAL_SECONDS)

    if members:
        result = cast(
            CursorResult[Any],
            await session.execute(
                update(TokenEnrichmentState)
                .where(
                    TokenEnrichmentState.mint_address.in_(members),
                    # Either below the lane (normal or nursery), or in it with
                    # a due time that has drifted beyond the lane's promise.
                    # The second case matters: a token already marked priority
                    # whose interval was set by an earlier tier would otherwise
                    # keep a six-hour due time forever and never be refreshed
                    # on the cadence its membership implies.
                    or_(
                        TokenEnrichmentState.priority < LANE_DISPLAY,
                        TokenEnrichmentState.next_refresh_at > clamp_to,
                    ),
                )
                .values(
                    # `greatest` so a re-clamp cannot pull a token in the
                    # one-shot Track Record lane back down before its attempt.
                    priority=func.greatest(TokenEnrichmentState.priority, LANE_DISPLAY),
                    next_refresh_at=func.least(TokenEnrichmentState.next_refresh_at, clamp_to),
                )
            ),
        )
        # Counts rows *touched*, which is promotions plus re-clamps.
        promoted += result.rowcount or 0

    demote = update(TokenEnrichmentState).where(TokenEnrichmentState.priority == LANE_DISPLAY)
    if members:
        demote = demote.where(TokenEnrichmentState.mint_address.not_in(members))
    # Demotion lands on NORMAL, not NURSERY: if the token is still inside the
    # fresh window the nursery pass below re-admits it within a minute, and if
    # it is not, it has no claim to a lane at all.
    result = cast(
        CursorResult[Any], await session.execute(demote.values(priority=LANE_NORMAL))
    )
    demoted = result.rowcount or 0

    return promoted, demoted


async def refresh_priority_lane(session: AsyncSession, *, now: datetime) -> PriorityMembership:
    """One pass: work out who is displayed, and make the table agree."""
    members, membership = await resolve_membership(session)
    promoted, demoted = await apply_membership(session, members, now=now)
    return PriorityMembership(
        radar=membership.radar,
        opportunities=membership.opportunities,
        paper=membership.paper,
        lab=membership.lab,
        total=membership.total,
        promoted=promoted,
        demoted=demoted,
        capped=membership.capped,
        established=membership.established,
    )


@dataclass(frozen=True, slots=True)
class NurseryMembership:
    """One nursery pass, reported so backpressure is visible, not silent."""

    members: int
    promoted: int
    evicted_aged: int
    #: Members trimmed because the lane was over capacity — the backpressure
    #: counter. A persistently non-zero value means launches outpace the cap
    #: and the oldest fresh tokens are losing their nursery time early.
    evicted_capacity: int
    capped: bool

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "members": self.members,
            "promoted": self.promoted,
            "evicted_aged": self.evicted_aged,
            "evicted_capacity": self.evicted_capacity,
            "capped": self.capped,
        }


async def refresh_nursery_lane(session: AsyncSession, *, now: datetime) -> NurseryMembership:
    """Maintain the fresh-token nursery: every newly discovered token's first
    `ENRICHMENT_TIER_FRESH_MAX_MINUTES` of prioritised observation.

    Discovery itself is the qualification — no score, no observation, no rank.
    That is deliberate: requiring any of those recreates the circularity this
    lane exists to break (a token needed observations to become interesting,
    and needed to be interesting to receive observations).

    Derived, never accumulated, exactly like the display lane above: age
    eviction and the capacity trim run every pass, so a token can overstay
    neither its window nor the cap. Registration puts a new token straight into
    the lane (`register_token`), so this pass is the *guarantee* — it re-admits
    anything the fast path missed (backfill after a worker outage, a demotion
    from the display lane) and trims any transient overshoot from concurrent
    registrations.

    When the cap bites, the *oldest* fresh tokens are trimmed first: they have
    already had the most nursery time, and a launch storm should cost tail
    minutes of observation rather than the first look at the newest tokens.
    """
    cap = settings.ENRICHMENT_NURSERY_MAX_TOKENS
    cutoff = now - timedelta(minutes=settings.ENRICHMENT_TIER_FRESH_MAX_MINUTES)

    # 1. Age eviction: the window is over; back to the age-tier cadence.
    # A token the Radar nursery still holds as OBSERVING is exempt: its whole
    # purpose is to be densely observed until its window decision (V4 Phase 2).
    still_observing = select(NurseryAdmission.token_id).where(
        NurseryAdmission.status == "observing"
    )
    result = cast(
        CursorResult[Any],
        await session.execute(
            update(TokenEnrichmentState)
            .where(
                TokenEnrichmentState.priority == LANE_NURSERY,
                TokenEnrichmentState.token_id == DiscoveredToken.id,
                DiscoveredToken.discovered_at < cutoff,
                TokenEnrichmentState.token_id.not_in(still_observing),
            )
            .values(priority=LANE_NORMAL)
        ),
    )
    evicted_aged = result.rowcount or 0

    # 2. Capacity trim, oldest first. `cap = 0` disables the lane entirely.
    overflow = (
        select(TokenEnrichmentState.id)
        .join(DiscoveredToken, TokenEnrichmentState.token_id == DiscoveredToken.id)
        .where(
            TokenEnrichmentState.priority == LANE_NURSERY,
            TokenEnrichmentState.token_id.not_in(still_observing),
        )
        .order_by(DiscoveredToken.discovered_at.desc(), TokenEnrichmentState.id)
        .offset(cap)
        .scalar_subquery()
    )
    result = cast(
        CursorResult[Any],
        await session.execute(
            update(TokenEnrichmentState)
            .where(TokenEnrichmentState.id.in_(overflow))
            .values(priority=LANE_NORMAL)
        ),
    )
    evicted_capacity = result.rowcount or 0

    members = int(
        await session.scalar(
            select(func.count())
            .select_from(TokenEnrichmentState)
            .where(TokenEnrichmentState.priority == LANE_NURSERY)
        )
        or 0
    )

    # 3. Promotion, newest first, into the remaining room. Only ACTIVE rows: a
    # dead-lettered fresh token re-enters through the requeue beat, not here.
    promoted = 0

    # --- observing members first, and unconditionally ------------------------
    # The Radar's observation window is a bounded, deliberate reservation
    # (admission rate x window, closed by expiry) — it must not queue behind
    # fresh-token churn. Measured 2026-08-24: the lane sat at 1,011 against a
    # cap of 1,000, so `room` went negative and four ACTIVE observing tokens
    # were never promoted at all — the window that exists to observe them was
    # collecting nothing. Capacity still bounds the fresh-by-age population
    # below; it no longer bounds the population the window is *about*.
    observing_waiting = (
        select(TokenEnrichmentState.id)
        .where(
            TokenEnrichmentState.status == EnrichmentStatus.ACTIVE,
            TokenEnrichmentState.priority == LANE_NORMAL,
            TokenEnrichmentState.token_id.in_(still_observing),
        )
        .scalar_subquery()
    )
    result = cast(
        CursorResult[Any],
        await session.execute(
            update(TokenEnrichmentState)
            .where(TokenEnrichmentState.id.in_(observing_waiting))
            .values(
                priority=LANE_NURSERY,
                next_refresh_at=func.least(TokenEnrichmentState.next_refresh_at, now),
            )
        ),
    )
    promoted += result.rowcount or 0
    members += promoted

    room = cap - members
    if room > 0:
        candidates = (
            select(TokenEnrichmentState.id)
            .join(DiscoveredToken, TokenEnrichmentState.token_id == DiscoveredToken.id)
            .where(
                TokenEnrichmentState.status == EnrichmentStatus.ACTIVE,
                TokenEnrichmentState.priority == LANE_NORMAL,
                DiscoveredToken.discovered_at >= cutoff,
            )
            .order_by(DiscoveredToken.discovered_at.desc(), TokenEnrichmentState.id)
            .limit(room)
            .scalar_subquery()
        )
        result = cast(
            CursorResult[Any],
            await session.execute(
                update(TokenEnrichmentState)
                .where(TokenEnrichmentState.id.in_(candidates))
                .values(
                    priority=LANE_NURSERY,
                    # Due immediately — a promoted token has, by definition,
                    # been waiting. A clamp, not an assignment.
                    next_refresh_at=func.least(TokenEnrichmentState.next_refresh_at, now),
                )
            ),
        )
        promoted = result.rowcount or 0

    return NurseryMembership(
        members=members + promoted,
        promoted=promoted,
        evicted_aged=evicted_aged,
        evicted_capacity=evicted_capacity,
        capped=members + promoted >= cap and cap > 0,
    )
