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
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.market import TokenEnrichmentState
from app.models.opportunity import Opportunity
from app.models.paper import PaperPosition
from app.models.radar import RadarToken
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
                    # Either not in the lane yet, or in it with a due time that
                    # has drifted beyond the lane's promise. The second case
                    # matters: a token already marked priority whose interval
                    # was set by an earlier tier would otherwise keep a
                    # six-hour due time forever and never be refreshed on the
                    # cadence its membership implies.
                    or_(
                        TokenEnrichmentState.priority == 0,
                        TokenEnrichmentState.next_refresh_at > clamp_to,
                    ),
                )
                .values(
                    priority=1,
                    next_refresh_at=func.least(TokenEnrichmentState.next_refresh_at, clamp_to),
                )
            ),
        )
        # Counts rows *touched*, which is promotions plus re-clamps.
        promoted = result.rowcount or 0

    demote = update(TokenEnrichmentState).where(TokenEnrichmentState.priority == 1)
    if members:
        demote = demote.where(TokenEnrichmentState.mint_address.not_in(members))
    result = cast(CursorResult[Any], await session.execute(demote.values(priority=0)))
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
        total=membership.total,
        promoted=promoted,
        demoted=demoted,
        capped=membership.capped,
    )
