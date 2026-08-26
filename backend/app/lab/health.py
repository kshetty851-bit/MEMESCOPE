"""Whether the Lab is producing evidence, or only producing ticks.

The Lab's beat is green whenever it runs. That says nothing about whether it is
still measuring anything, and on 2026-08-26 the difference was enormous: 162 of
224 open positions were being skipped every tick as stale, so 72% of the book sat
frozen at its last healthy price while every liveness signal in the platform read
normal.

Four questions, each chosen because it has a specific way of going silently
wrong, and each answerable from the Lab's own tables:

  STALE      what fraction of the open book cannot be marked at all. The failure
             is self-selecting — a dying token stops being enriched, so its
             snapshot goes stale, so it is never marked again — which means the
             positions this hides are exactly the ones that matter.

  ENTRIES    decisions are still being made. Zero decisions is normal for a
             minute and abnormal for an hour, and nothing else in the platform
             would say so.

  EXITS      positions are still closing. A book that only grows is a book whose
             exits have stopped firing, which is invisible until the capital is
             gone.

  MARKS      what fraction of open VALUE is backed by a real sell quote rather
             than by the CPMM model over reported liquidity. This is the number
             that decides whether the leaderboard can be trusted at all, and
             before the sellability sweep existed it was zero without anyone
             being able to see that.

## It reports; it does not judge

Every function returns measurements. The thresholds that turn a number into a
condition live in `hq_ops`, with every other threshold, so a reader comparing
"amber at what?" across the platform finds one answer in one place.

## Unmeasurable is not healthy

A query that cannot run returns `None`, never zero. Zero stale positions and "we
could not count the stale positions" are opposite readings, and the whole reason
this module exists is that the second one was being displayed as the first.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.lab import spec
from app.lab.execution import STALE_GUARD_SECONDS
from app.lab.sellability import CONTEXT as MARK_CONTEXT
from app.lab.sellability import MAX_QUOTE_AGE
from app.models.lab import LabDecision, LabPosition, LabStrategy, LabTournament
from app.models.market import TokenMarketSnapshot
from app.models.research_data import ResearchQuote

logger = get_logger(__name__)

#: How long a Lab with open positions may go without a decision before the
#: silence is worth reporting. Checkpoints run at admission, +30 and +60 minutes,
#: so an hour of nothing means no token reached any of them — possible on a quiet
#: market, and worth a look either way.
ENTRY_SILENCE = timedelta(hours=1)

#: How long a book may go without a single close. Every trading strategy carries
#: a time exit of 6 hours or less, so nothing closing in three is the exits
#: themselves having stopped rather than a slow market.
EXIT_SILENCE = timedelta(hours=3)


@dataclass(frozen=True, slots=True)
class LabHealth:
    """One reading. `None` anywhere means unmeasured, never zero."""

    measured: bool
    detail: str
    open_positions: int | None = None
    #: Open positions whose freshest market print is already too old to act on.
    stale_positions: int | None = None
    stale_pct: float | None = None
    #: Fraction of open VALUE priced from a real sell quote rather than a model.
    quote_backed_pct: float | None = None
    minutes_since_decision: float | None = None
    minutes_since_close: float | None = None
    spec_version: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "measured": self.measured,
            "detail": self.detail,
            "open_positions": self.open_positions,
            "stale_positions": self.stale_positions,
            "stale_pct": self.stale_pct,
            "quote_backed_pct": self.quote_backed_pct,
            "minutes_since_decision": self.minutes_since_decision,
            "minutes_since_close": self.minutes_since_close,
            "spec_version": self.spec_version,
        }


async def read(session: AsyncSession, *, now: datetime | None = None) -> LabHealth:
    """Measure the four signals for the CURRENT tournament.

    Scoped by `spec_version` like every other Lab read: a dormant record's
    positions are not this tournament's book, and counting them would report a
    finished experiment's staleness as a live problem.
    """
    now = now or datetime.now(UTC)
    try:
        tournament = (await session.execute(
            select(LabTournament).where(LabTournament.spec_version == spec.SPEC_VERSION)
        )).scalars().first()
        if tournament is None:
            return LabHealth(measured=False, detail="No tournament is activated.")

        rows = list((await session.execute(
            select(LabPosition.mint_address, LabPosition.quantity_remaining,
                   LabPosition.size_usd, LabPosition.last_open_value_usd)
            .join(LabStrategy, LabStrategy.id == LabPosition.strategy_row_id)
            .where(LabStrategy.tournament_id == tournament.id,
                   LabPosition.status == "open")
        )).all())
        open_count = len(rows)

        stale = await _stale_count(session, [r.mint_address for r in rows], now)
        quote_backed = await _quote_backed_pct(session, rows, now)
        since_decision = await _minutes_since(
            session, select(func.max(LabDecision.checkpoint_at))
            .join(LabStrategy, LabStrategy.id == LabDecision.strategy_row_id)
            .where(LabStrategy.tournament_id == tournament.id), now)
        since_close = await _minutes_since(
            session, select(func.max(LabPosition.closed_at))
            .join(LabStrategy, LabStrategy.id == LabPosition.strategy_row_id)
            .where(LabStrategy.tournament_id == tournament.id), now)
    except Exception as exc:  # noqa: BLE001 - unmeasurable is not healthy
        logger.warning("lab_health_unreadable", error=str(exc))
        return LabHealth(measured=False, detail=f"Lab health could not be read: {exc}")

    stale_pct = (round(stale / open_count * 100, 1)
                 if open_count and stale is not None else None)
    return LabHealth(
        measured=True,
        detail=(f"{open_count} open, {stale if stale is not None else '?'} unmarkable, "
                f"{quote_backed if quote_backed is not None else '?'}% quote-backed."),
        open_positions=open_count,
        stale_positions=stale,
        stale_pct=stale_pct,
        quote_backed_pct=quote_backed,
        minutes_since_decision=since_decision,
        minutes_since_close=since_close,
        spec_version=tournament.spec_version,
    )


async def _stale_count(
    session: AsyncSession, mints: list[str], now: datetime
) -> int | None:
    """Open positions whose freshest print is already too old to act on.

    Counted the same way `_mark` decides to skip one, so this number IS the
    number of positions the next tick will refuse to evaluate — not an
    approximation of it.
    """
    if not mints:
        return 0
    cutoff = now - timedelta(seconds=STALE_GUARD_SECONDS)
    latest = (
        select(TokenMarketSnapshot.mint_address,
               func.max(TokenMarketSnapshot.captured_at).label("captured_at"))
        .where(TokenMarketSnapshot.mint_address.in_(mints))
        .group_by(TokenMarketSnapshot.mint_address)
        .subquery()
    )
    fresh = set((await session.execute(
        select(latest.c.mint_address).where(latest.c.captured_at >= cutoff)
    )).scalars())
    # A mint with NO snapshot at all is stale too — it cannot be marked either.
    return sum(1 for mint in mints if mint not in fresh)


async def _quote_backed_pct(
    session: AsyncSession, rows: list, now: datetime
) -> float | None:
    """Fraction of open VALUE priced from a real sell quote, not a model.

    By value rather than by count on purpose: ten dust positions backed by
    quotes and one large one backed by a model is not a well-evidenced book, and
    a count would call it 91% healthy.
    """
    if not rows:
        return 100.0
    mints = [r.mint_address for r in rows]
    quoted = set((await session.execute(
        select(ResearchQuote.mint_address).where(
            ResearchQuote.mint_address.in_(mints),
            ResearchQuote.context == MARK_CONTEXT,
            ResearchQuote.side == "sell",
            ResearchQuote.ok.is_(True),
            ResearchQuote.requested_at >= now - MAX_QUOTE_AGE,
        ).distinct()
    )).scalars())

    total = Decimal(0)
    backed = Decimal(0)
    for row in rows:
        value = Decimal(str(row.last_open_value_usd if row.last_open_value_usd
                            is not None else row.size_usd or 0))
        total += value
        if row.mint_address in quoted:
            backed += value
    if total <= 0:
        return None
    return round(float(backed / total * 100), 1)


async def _minutes_since(session: AsyncSession, stmt, now: datetime) -> float | None:
    """Minutes since the newest row the statement selects, or None if never."""
    at = await session.scalar(stmt)
    if at is None:
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    return round((now - at).total_seconds() / 60, 1)


__all__ = ["ENTRY_SILENCE", "EXIT_SILENCE", "LabHealth", "read"]
