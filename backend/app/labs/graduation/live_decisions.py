"""Mirror the graduation arms' entries into `lab_decisions`.

`RealWalletDriver` does not choose anything. It buys the most recent mint a Lab
strategy already chose, read from `lab_decisions` and keyed by `strategy_id`.
The graduation lab writes nothing there, so its arms were invisible to the real
wallet no matter what was nominated. This is the only thing that connects them.

## It mirrors, it does not decide

A row is written here only because `tournament.py` already opened a paper
position under one of `live_spec.PAPER_BOOKS`, and it is written under the live
arm that book feeds. The band rule, the impact refusal and the
slot cap were all evaluated there. Writing a second copy of the entry rule would
be a second answer, and the first time the two disagreed the real book and the
paper record would stop describing the same strategy.

## Why it writes in the entry's own transaction

The clock is the strategy, and it starts when the WALLET fills, not when the
paper book did. Replayed over this arm's own 145 trades, a buy 60 seconds late
still exits five minutes after ITSELF — six minutes after graduation — and
wiped the wallet in 51% of draws. Written inline, the decision is on disk the
instant the paper position is, and the driver's own latency is all that remains.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.labs.graduation import live_spec as spec
from app.models.lab import LabDecision, LabStrategy, LabTournament

logger = get_logger(__name__)

#: When the record is judged. Required by the column and meaningless here —
#: this registry mirrors an arm the graduation lab judges on its own board.
SNAPSHOT_HOURS = 24


@dataclass(frozen=True, slots=True)
class Mirrored:
    """One paper entry worth telling the real wallet about."""

    #: The live arm this entry feeds (`live_spec.MIRRORS[book]`).
    strategy_id: str
    mint: str
    opened_at: datetime
    liquidity_usd: Decimal | None
    impact: Decimal | None
    price_native: Decimal | None


async def strategy_row_id(session: AsyncSession,
                          s: spec.Strategy) -> uuid.UUID:
    """The `lab_strategies` row this registry writes under, created on first use.

    Its own tournament, with its own `spec_version` and `spec_hash`. Every
    query that could reach these rows is scoped by one of those or by
    `tournament_id`, so V7 cannot see this and this cannot see V7 — which is
    the whole reason the arm is not simply added to `app.lab.spec`.
    """
    from app.lab.spec import rules_json

    tournament = (await session.execute(
        select(LabTournament).where(
            LabTournament.spec_version == spec.SPEC_VERSION)
    )).scalars().first()
    if tournament is None:
        tournament = LabTournament(
            spec_version=spec.SPEC_VERSION, spec_hash=spec.SPEC_HASH,
            valid_from=(started := datetime.now(UTC)),
            snapshot_at=started + timedelta(hours=SNAPSHOT_HOURS),
            status="active",
            protocol_note=(
                "Graduation lab " + " and ".join(spec.PAPER_BOOKS.values())
                + ", mirrored for the real wallet. "
                "NOT CALLED by the lab's own gate; registration is not a "
                "recommendation."),
        )
        session.add(tournament)
        await session.flush()
        logger.warning("gradlive_tournament_created",
                       spec_version=spec.SPEC_VERSION,
                       spec_hash=spec.SPEC_HASH[:16])

    row = (await session.execute(
        select(LabStrategy).where(
            LabStrategy.tournament_id == tournament.id,
            LabStrategy.strategy_id == s.id)
    )).scalars().first()
    if row is None:
        row = LabStrategy(
            tournament_id=tournament.id, strategy_id=s.id, name=s.name,
            version=spec.SPEC_VERSION, spec_hash=spec.SPEC_HASH,
            checkpoint_minutes=s.checkpoint_minutes, size_usd=s.size_usd,
            max_concurrent=s.max_concurrent,
            max_exposure_usd=s.max_exposure_usd,
            rules=rules_json(s), starting_equity=spec.STARTING_EQUITY,
            cash=spec.STARTING_EQUITY, peak_equity=spec.STARTING_EQUITY,
            status="active",
        )
        session.add(row)
        await session.flush()
        logger.warning("gradlive_strategy_created", strategy_id=s.id)
    return row.id


async def record(session: AsyncSession, entries: list[Mirrored]) -> int:
    """Write one decision per paper entry. Idempotent by the table's own key.

    The unique constraint is (strategy_row_id, mint_address, checkpoint_at) and
    `checkpoint_at` is the paper position's `opened_at`, so a replayed tick
    cannot double-write and a mint the arm re-enters later is a new row.
    """
    written = 0
    now = datetime.now(UTC)
    for s in spec.STRATEGIES:
        written += await _record(session, s, [e for e in entries
                                              if e.strategy_id == s.id], now)
    if written:
        logger.warning("gradlive_decisions_written", count=written,
                       mints=[e.mint for e in entries][:5])
    return written


async def _record(session: AsyncSession, s: spec.Strategy,
                  entries: list[Mirrored], now: datetime) -> int:
    """`record` for one live arm."""
    if not entries:
        return 0
    row_id = await strategy_row_id(session, s)
    seen = set((await session.execute(
        select(LabDecision.mint_address, LabDecision.checkpoint_at)
        .where(LabDecision.strategy_row_id == row_id,
               LabDecision.mint_address.in_([e.mint for e in entries]))
    )).all())

    written = 0
    for e in entries:
        if (e.mint, e.opened_at) in seen:
            continue
        session.add(LabDecision(
            strategy_row_id=row_id,
            strategy_id=s.id,
            mint_address=e.mint,
            # Graduation mints are not necessarily in `discovered_tokens`, and
            # the column is nullable precisely so a lab with its own universe
            # can write here without inventing a row in someone else's table.
            token_id=None,
            checkpoint_at=e.opened_at,
            checkpoint_minutes=0,
            decided_at=now,
            eligible=True,
            # Exactly what the entry rule read, so the decision can be checked
            # against the paper position rather than taken on trust.
            features={
                "paper_book": spec.PAPER_BOOKS[s.id],
                "pool_floor_usd": spec.pool_floor(s.id),
                "liquidity_usd": (None if e.liquidity_usd is None
                                  else str(e.liquidity_usd)),
                "impact_open": None if e.impact is None else str(e.impact),
                "price_native": (None if e.price_native is None
                                 else str(e.price_native)),
                "hold_minutes": spec.hold_minutes(s),
            },
            requested_size_usd=s.size_usd,
        ))
        written += 1
    return written
