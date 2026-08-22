"""Daily, weekly, lifetime — and "what happened while I was away".

§12 and §13. One builder, three windows, because a daily report and a lifetime
report differ only in where the window starts and in which trends are worth
computing over it. Three functions would be three places for the same figure to
be derived slightly differently, and a weekly P&L that disagreed with the sum
of its days is worse than no weekly report.

── A FIGURE THAT COULD NOT BE DERIVED IS `None`, NEVER `0` ──────────────

Every numeric field is optional. `targets_hit: 0` means the window was measured
and nothing hit; `targets_hit: None` means nobody could look. Rendering the
second as the first would let an outage read as a quiet day, and a quiet day is
a claim about the experiment.

── WHY THE REPORTS ARE COMPUTED, NOT STORED ─────────────────────────────

There is no `karthik_reports` table. A stored report is a second source of
truth that stops agreeing with the positions it summarises the moment one is
corrected, and the whole surface is cheap to derive: the positions are already
indexed by wallet and the windows are small. §8's `report_rerun` repair exists
for a *scheduled delivery* that did not produce a row, not for this.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.karthik_ops import tables
from app.karthik_ops.integrity import Integrity
from app.karthik_ops.monitor import wallet_screen
from app.karthik_ops.wallet import Binding

#: The three windows §12 names, plus the one §13 does. `while_away` is not a
#: fixed duration — it is "since the reader last looked" — so it carries its
#: start from the caller rather than from this table.
WINDOWS: dict[str, timedelta | None] = {
    "daily": timedelta(days=1),
    "weekly": timedelta(days=7),
    "lifetime": None,
}


@dataclass(slots=True)
class Report:
    """One window's figures. Every number optional, every absence explained."""

    window: str
    since: str | None
    until: str
    measured: bool
    detail: str

    starting_equity_usd: str | None = None
    ending_equity_usd: str | None = None
    pnl_usd: str | None = None

    opportunities: int | None = None
    entered: int | None = None
    targets_hit: int | None = None
    dead_zero: int | None = None
    open_positions: int | None = None
    closed_positions: int | None = None

    best_trade: dict[str, object] | None = None
    worst_trade: dict[str, object] | None = None
    average_hold_seconds: float | None = None
    target_hit_rate: float | None = None
    dead_rate: float | None = None
    cash_utilisation: float | None = None

    bugs_detected: int | None = None
    repairs_performed: int | None = None
    owner_attention: int | None = None
    integrity: dict[str, object] | None = None

    #: Weekly and lifetime only: the per-day series §12 asks for. Empty on a
    #: daily report rather than a single point, which would imply a trend.
    daily_series: list[dict[str, object]] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _unavailable(window: str, binding: Binding, now: datetime) -> Report:
    return Report(
        window=window,
        since=None,
        until=now.isoformat(),
        measured=False,
        detail=binding.detail,
    )


async def build(
    session: AsyncSession,
    binding: Binding,
    *,
    window: str,
    now: datetime | None = None,
    since: datetime | None = None,
    integrity: Integrity | None = None,
    bugs: int | None = None,
    repairs: int | None = None,
    owner_attention: int | None = None,
) -> Report:
    """One window's report.

    `since` overrides the window's own start, which is what makes §13's
    "while you were away" the same code path as the other three rather than a
    fourth implementation of the same arithmetic.
    """
    clock = now or datetime.now(UTC)
    if not binding.readable:
        return _unavailable(window, binding, clock)

    span = WINDOWS.get(window)
    start = since or (clock - span if span else binding.started_at)

    positions = tables.karthik_positions
    rows = (
        await session.execute(
            select(
                positions.c.mint_address,
                positions.c.opened_at,
                positions.c.closed_at,
                positions.c.cost_basis,
                positions.c.exit_proceeds_usd,
                positions.c.exit_reason,
            ).where(positions.c.wallet_id == binding.wallet_id)
        )
    ).all()

    opportunities = tables.karthik_opportunities
    seen = (
        await session.execute(
            select(
                opportunities.c.decision,
                opportunities.c.track_record_at,
            ).where(opportunities.c.wallet_id == binding.wallet_id)
        )
    ).all()

    # Opened *or* closed inside the window. A position that opened last week and
    # hit its target this morning belongs in today's report; filtering on
    # `opened_at` alone would drop exactly the trades a reader came for.
    def touched(row: Row[Any]) -> bool:
        if start is None:
            return True
        return row.opened_at >= start or (row.closed_at is not None and row.closed_at >= start)

    windowed = [row for row in rows if touched(row)]
    closed = [row for row in windowed if row.closed_at is not None]
    settled = [row for row in closed if row.exit_proceeds_usd is not None]
    targets = [row for row in closed if row.exit_reason == "target_1_25x"]
    dead = [row for row in closed if row.exit_reason == "dead_zero"]

    pnl = sum((r.exit_proceeds_usd - r.cost_basis for r in settled), Decimal(0))

    book = await wallet_screen(session, binding)
    ending = Decimal(str(book.values["cash_usd"])) if book.measured else None

    def trade(row: Row[Any]) -> dict[str, object]:
        return {
            "mint": row.mint_address,
            "pnl_usd": str(row.exit_proceeds_usd - row.cost_basis),
            "proceeds_usd": str(row.exit_proceeds_usd),
            "closed_at": row.closed_at.isoformat() if row.closed_at else None,
        }

    by_pnl = sorted(settled, key=lambda r: r.exit_proceeds_usd - r.cost_basis)
    holds = [
        (row.closed_at - row.opened_at).total_seconds() for row in closed if row.closed_at
    ]
    allocated = Decimal(str(book.values["allocated_usd"])) if book.measured else None
    start_capital = binding.starting_balance or Decimal(0)
    # The wallet records one decision per admission, so an "opportunity" is a
    # counted fact rather than an estimate.
    opportunities_seen = [row for row in seen if start is None or row.track_record_at >= start]

    report = Report(
        window=window,
        since=start.isoformat() if start else None,
        until=clock.isoformat(),
        measured=True,
        detail=f"{len(windowed)} positions touched this window.",
        # There is no equity series table, so a *starting* equity for an
        # arbitrary window cannot be read. Stated as absent rather than
        # back-computed from P&L, which would only ever restate the P&L.
        starting_equity_usd=str(start_capital) if window == "lifetime" else None,
        ending_equity_usd=str(ending) if ending is not None else None,
        pnl_usd=str(pnl),
        opportunities=len(opportunities_seen),
        entered=len([row for row in opportunities_seen if row.decision == tables.ENTERED]),
        targets_hit=len(targets),
        dead_zero=len(dead),
        open_positions=len([row for row in rows if row.closed_at is None]),
        closed_positions=len(closed),
        best_trade=trade(by_pnl[-1]) if by_pnl else None,
        worst_trade=trade(by_pnl[0]) if by_pnl else None,
        average_hold_seconds=sum(holds) / len(holds) if holds else None,
        target_hit_rate=len(targets) / len(closed) if closed else None,
        dead_rate=len(dead) / len(closed) if closed else None,
        cash_utilisation=(
            float(allocated / start_capital)
            if allocated is not None and start_capital
            else None
        ),
        bugs_detected=bugs,
        repairs_performed=repairs,
        owner_attention=owner_attention,
        integrity=(
            {"score": integrity.score, "band": integrity.band, "headline": integrity.headline}
            if integrity
            else None
        ),
    )

    if window in ("weekly", "lifetime") and start is not None:
        report.daily_series = _by_day(closed, start, clock)
    return report


def _count(value: object) -> int:
    """Read an int back out of a `dict[str, object]` accumulator.

    The day rows are heterogeneous — a date string, a money string, two
    counters — so the dict is `object`-valued and the counters need narrowing
    on the way out. One helper rather than a cast at each use, so the
    assumption is stated once.
    """
    return int(value) if isinstance(value, (int, str)) else 0


def _by_day(
    closed: list[Row[Any]], start: datetime, until: datetime
) -> list[dict[str, object]]:
    """P&L and target hits per calendar day, oldest first.

    Only days inside the window appear, and a day with no closed trade appears
    with zeroes rather than being skipped — a trend line with holes in it reads
    as a shorter experiment, not as a quiet Tuesday.
    """
    days: dict[str, dict[str, object]] = {}
    cursor = start
    while cursor.date() <= until.date():
        days[cursor.date().isoformat()] = {
            "date": cursor.date().isoformat(),
            "pnl_usd": "0",
            "targets": 0,
            "closed": 0,
        }
        cursor += timedelta(days=1)

    for row in closed:
        if row.closed_at is None or row.exit_proceeds_usd is None:
            continue
        key = row.closed_at.date().isoformat()
        day = days.get(key)
        if day is None:
            continue
        day["pnl_usd"] = str(
            Decimal(str(day["pnl_usd"])) + (row.exit_proceeds_usd - row.cost_basis)
        )
        day["closed"] = _count(day["closed"]) + 1
        if row.exit_reason == "target_1_25x":
            day["targets"] = _count(day["targets"]) + 1

    return list(days.values())


@dataclass(slots=True)
class WhileAway:
    """§13, which is a report with a reader-supplied start.

    Kept as its own type rather than reusing `Report` because it answers a
    different question — "what changed since I last looked" — and half of
    `Report`'s fields (hold time, utilisation, trends) are meaningless over an
    arbitrary gap. Reusing the shape would fill a panel with fields nobody can
    interpret.
    """

    since: str | None
    until: str
    measured: bool
    detail: str
    opportunities: int | None = None
    new_trades: int | None = None
    targets_hit: int | None = None
    dead_positions: int | None = None
    pnl_usd: str | None = None
    biggest_winner: dict[str, object] | None = None
    biggest_loss: dict[str, object] | None = None
    bugs_found: int | None = None
    bugs_fixed: int | None = None
    owner_attention: int | None = None
    integrity_score: int | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


async def while_away(
    session: AsyncSession,
    binding: Binding,
    *,
    since: datetime | None,
    now: datetime | None = None,
    integrity: Integrity | None = None,
    bugs: int | None = None,
    repairs: int | None = None,
    owner_attention: int | None = None,
) -> WhileAway:
    """What changed since the reader's previous visit.

    `since` is `None` on a first visit, and that is reported as a first visit
    rather than as "nothing happened" — the two are indistinguishable in the
    numbers and completely different to a reader.
    """
    clock = now or datetime.now(UTC)
    if not binding.readable:
        return WhileAway(
            since=since.isoformat() if since else None,
            until=clock.isoformat(),
            measured=False,
            detail=binding.detail,
        )
    if since is None:
        return WhileAway(
            since=None,
            until=clock.isoformat(),
            measured=False,
            detail=(
                "First visit on this device — there is no previous session to compare against."
            ),
        )

    report = await build(
        session,
        binding,
        window="while_away",
        now=clock,
        since=since,
        integrity=integrity,
        bugs=bugs,
        repairs=repairs,
        owner_attention=owner_attention,
    )
    return WhileAway(
        since=report.since,
        until=report.until,
        measured=report.measured,
        detail=report.detail,
        opportunities=report.opportunities,
        new_trades=report.entered,
        targets_hit=report.targets_hit,
        dead_positions=report.dead_zero,
        pnl_usd=report.pnl_usd,
        biggest_winner=report.best_trade,
        biggest_loss=report.worst_trade,
        bugs_found=bugs,
        bugs_fixed=repairs,
        owner_attention=owner_attention,
        integrity_score=integrity.score if integrity else None,
    )
