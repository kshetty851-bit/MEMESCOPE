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

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.market import (
    LANE_DISPLAY,
    LANE_NORMAL,
    LANE_NURSERY,
    EnrichmentStatus,
    TokenEnrichmentState,
)
from app.models.opportunity import Opportunity
from app.models.paper import PaperPosition
from app.models.radar import RadarToken
from app.models.token import DiscoveredToken
from app.opportunities.models import LIVE_STATUSES
from app.paper.models import PositionStatus


@dataclass(frozen=True, slots=True)
class PriorityMembership:
    """Who is in the lane, and why. Reported so the lane is auditable."""

    radar: int
    opportunities: int
    paper: int
    total: int
    promoted: int
    demoted: int
    capped: bool

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "radar": self.radar,
            "opportunities": self.opportunities,
            "paper": self.paper,
            "total": self.total,
            "promoted": self.promoted,
            "demoted": self.demoted,
            "capped": self.capped,
        }


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

    # Open paper positions first. A paper holding is not merely displayed: its
    # next quote can settle an existing position, so allowing the Radar or an
    # opportunity list to consume the cap first can strand it on an old tier.
    # The lane is still one bounded, derived set; this only gives the wallet's
    # already-committed capital precedence within that set.
    ordered: list[str] = []
    seen: set[str] = set()
    for mint in [*paper_mints, *radar_mints, *opportunity_mints]:
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
        total=len(members),
        promoted=0,
        demoted=0,
        capped=capped,
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
        promoted = result.rowcount or 0

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


async def reprime_open_positions(
    session: AsyncSession, mints: Sequence[str], *, now: datetime
) -> int:
    """Put stale open paper positions at the head of the queue. Returns rows moved.

    ── WHY THIS IS SEPARATE FROM `apply_membership` ────────────────────────

    That method clamps a member's due time to `now + priority_interval`, which
    is the right promise for a token that is merely *displayed*: it says "you
    will be refreshed on the lane's cadence". It is the wrong promise for a
    position holding capital that has already gone dark, because it schedules
    the refresh fifteen seconds into the future and then sorts that row behind
    every already-overdue member of the same lane.

    On 2026-08-21 the feed returned after a 125-minute stop and 62 of 106 open
    positions waited a further 44 minutes for their first observation. The lane
    ordering was correct throughout and paper positions had sorted first since
    August; what was missing was any statement that these particular rows
    needed a quote *now*, and any check that they got one.

    So this clamps to `now` rather than to a future interval — due immediately,
    which within `claim_due`'s `ORDER BY priority DESC, next_refresh_at ASC`
    puts them at the head of the highest lane they can occupy.

    It is a **clamp and a `greatest`**, exactly like `apply_membership`: it can
    only ever bring a refresh forward and can never pull a token down out of a
    higher lane. Calling it repeatedly is a no-op once the rows are already due.

    The caller decides which mints are stale — see
    `paper.market_health.stale_open_mints`, which excludes the unpriceable, so
    this never spends the head of the queue re-asking for a pool that has
    answered empty three thousand times.
    """
    unique = list(dict.fromkeys(mints))
    if not unique:
        return 0
    result = cast(
        CursorResult[Any],
        await session.execute(
            update(TokenEnrichmentState)
            .where(
                TokenEnrichmentState.mint_address.in_(unique),
                TokenEnrichmentState.status == EnrichmentStatus.ACTIVE,
                # Nothing to do for a row already at the head of the queue.
                # The predicate is what makes a repeated pass write no rows
                # and produce no dead tuples.
                or_(
                    TokenEnrichmentState.priority < LANE_DISPLAY,
                    TokenEnrichmentState.next_refresh_at > now,
                ),
            )
            .values(
                priority=func.greatest(TokenEnrichmentState.priority, LANE_DISPLAY),
                next_refresh_at=func.least(TokenEnrichmentState.next_refresh_at, now),
            )
        ),
    )
    return result.rowcount or 0


async def refresh_priority_lane(session: AsyncSession, *, now: datetime) -> PriorityMembership:
    """One pass: work out who is displayed, and make the table agree."""
    members, membership = await resolve_membership(session)
    promoted, demoted = await apply_membership(session, members, now=now)
    return PriorityMembership(
        radar=membership.radar,
        opportunities=membership.opportunities,
        paper=membership.paper,
        total=membership.total,
        promoted=promoted,
        demoted=demoted,
        capped=membership.capped,
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
    result = cast(
        CursorResult[Any],
        await session.execute(
            update(TokenEnrichmentState)
            .where(
                TokenEnrichmentState.priority == LANE_NURSERY,
                TokenEnrichmentState.token_id == DiscoveredToken.id,
                DiscoveredToken.discovered_at < cutoff,
            )
            .values(priority=LANE_NORMAL)
        ),
    )
    evicted_aged = result.rowcount or 0

    # 2. Capacity trim, oldest first. `cap = 0` disables the lane entirely.
    overflow = (
        select(TokenEnrichmentState.id)
        .join(DiscoveredToken, TokenEnrichmentState.token_id == DiscoveredToken.id)
        .where(TokenEnrichmentState.priority == LANE_NURSERY)
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
