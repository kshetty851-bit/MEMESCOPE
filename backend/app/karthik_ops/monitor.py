"""What Karthik actually looks at, every tick.

§15's list, turned into readings that map one-to-one onto the six screens in
his office. Keeping the mapping exact is deliberate: a monitor in the room that
shows something no endpoint publishes is a monitor showing a drawing, and the
whole point of the room is that it is not one.

── EVERY READING CARRIES `measured` ─────────────────────────────────────

Copied from `hq_ops.schemas`, and for the identical reason. "We looked and
there are no open positions" and "we could not look" are different facts, and a
screen that renders the second as `0` is a screen that lies during exactly the
outage it exists to reveal.

── NOTHING HERE WRITES ──────────────────────────────────────────────────

Every statement in this module is a `SELECT`, against the three tables
`tables.py` declares and no others. Karthik's authority to *act* is
`authority.SAFE_REPAIRS`, evaluated elsewhere and gated on autonomy; the
reading path has no write in it at all, which is what makes it safe to poll.

── WHY IT REUSES `hq_ops.probe` FOR INFRASTRUCTURE ──────────────────────

§26 forbids a second global scheduler, and the same argument applies to a
second prober: Redis, Postgres, the worker and the scheduler are the same
components whether Karthik or Sentinel is asking, and two implementations would
eventually disagree about whether the worker is up. Screen 5 renders `hq_ops`'s
reading with Karthik's own wallet-loop state beside it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.karthik_ops import tables
from app.karthik_ops.wallet import Binding
from app.models.market import TokenMarketSnapshot

#: How old a quote may be before an open position is being valued on a guess.
#: Deliberately generous — this is the threshold for calling a *valuation*
#: unreliable, not for calling a trade, and a tighter number would fire on
#: every ordinary provider hiccup.
QUOTE_STALE_AFTER = timedelta(minutes=10)

#: How long after a Track Record admission a decision is expected. Beyond this
#: the entry is late, which is a data-quality fact about the experiment rather
#: than a fault in it.
DECISION_EXPECTED_WITHIN = timedelta(minutes=5)

#: How many rows a screen shows. A monitor is not a table dump.
SCREEN_ROWS = 12

_OPEN = "open"


@dataclass(frozen=True, slots=True)
class Reading:
    """A screen's worth of state: values, whether they were measured, and why."""

    measured: bool
    detail: str
    values: dict[str, object] = field(default_factory=dict)
    rows: list[dict[str, object]] = field(default_factory=list)


def _unavailable(binding: Binding) -> Reading:
    """The reading every screen gets while Karthik has no wallet.

    One function rather than six copies of the same sentence, so the room can
    never show five screens saying NOT DESIGNATED and a sixth quietly showing
    zeroes because somebody forgot a branch.
    """
    return Reading(measured=False, detail=binding.detail)


_POS = tables.karthik_positions
_OPP = tables.karthik_opportunities


async def wallet_screen(session: AsyncSession, binding: Binding) -> Reading:
    """SCREEN 1 — equity, cash, allocated, realised, unrealised, open, closed.

    Everything is derived from position rows rather than read from a stored
    balance, matching the Original Paper Wallet's rule and for its reason: a
    stored balance is a second source of truth that drifts from its own trades
    the moment one write lands without the other.
    """
    if not binding.readable:
        return _unavailable(binding)

    rows = (
        await session.execute(
            select(
                _POS.c.cost_basis,
                _POS.c.exit_proceeds_usd,
                _POS.c.closed_at,
            ).where(_POS.c.wallet_id == binding.wallet_id)
        )
    ).all()

    open_rows = [row for row in rows if row.closed_at is None]
    closed_rows = [row for row in rows if row.closed_at is not None]
    # A closed row with no recorded proceeds has *unknown* proceeds, not zero.
    # Excluded from realised P&L and counted separately, so a wallet with an
    # unsettled exit reports a smaller figure and says why.
    settled = [row for row in closed_rows if row.exit_proceeds_usd is not None]

    allocated = sum((row.cost_basis for row in open_rows), Decimal(0))
    realised = sum(
        (row.exit_proceeds_usd - row.cost_basis for row in settled),
        Decimal(0),
    )
    start = binding.starting_balance or Decimal(0)
    cash = start + realised - allocated

    unsettled = len(closed_rows) - len(settled)
    return Reading(
        measured=True,
        detail=(
            f"Derived from {len(rows)} position rows"
            + (
                f"; {unsettled} closed without recorded proceeds and excluded from realised "
                f"P&L."
                if unsettled
                else "."
            )
        ),
        values={
            "starting_capital_usd": str(start),
            "cash_usd": str(cash),
            "allocated_usd": str(allocated),
            "realised_pnl_usd": str(realised),
            # Unrealised needs a current price per open mint, which is Screen 3's
            # job. Reported as None rather than 0 — an unpriced book is not a
            # flat book.
            "unrealised_pnl_usd": None,
            "open_positions": len(open_rows),
            "closed_positions": len(closed_rows),
            "closed_without_proceeds": unsettled,
        },
    )


async def feed_screen(session: AsyncSession, binding: Binding) -> Reading:
    """SCREEN 2 — the live Track Record feed, and what the wallet decided.

    Reads the wallet's own `karthik_opportunities`, which records one decision
    per admission. That is why this screen can say *skipped, and why* rather
    than only "no position": a mint without a position is not evidence of a
    miss, and a screen that presented it as one would be inventing a defect.
    """
    if not binding.readable:
        return _unavailable(binding)

    rows = (
        await session.execute(
            select(
                _OPP.c.mint_address,
                _OPP.c.track_record_at,
                _OPP.c.decision,
                _OPP.c.decided_at,
            )
            .where(_OPP.c.wallet_id == binding.wallet_id)
            .order_by(_OPP.c.track_record_at.desc())
            .limit(SCREEN_ROWS)
        )
    ).all()

    return Reading(
        measured=True,
        detail=f"{len(rows)} most recent Track Record decisions.",
        values={"eligible": None},
        rows=[
            {
                "mint": row.mint_address,
                "detected_at": row.track_record_at.isoformat(),
                "outcome": "entered" if row.decision == tables.ENTERED else "skipped",
                # The wallet's own decision string, unedited. A rephrasing here
                # would be this layer explaining a decision it did not make.
                "reason": row.decision,
                "delay_seconds": (row.decided_at - row.track_record_at).total_seconds(),
            }
            for row in rows
        ],
    )


async def positions_screen(session: AsyncSession, binding: Binding) -> Reading:
    """SCREEN 3 — open positions, their multiple, and how fresh the price is."""
    if not binding.readable:
        return _unavailable(binding)

    open_rows = (
        await session.execute(
            select(
                _POS.c.mint_address,
                _POS.c.entry_price,
                _POS.c.quantity,
                _POS.c.cost_basis,
                _POS.c.target_price,
            ).where(_POS.c.wallet_id == binding.wallet_id, _POS.c.closed_at.is_(None))
        )
    ).all()

    if not open_rows:
        return Reading(measured=True, detail="No open positions.", rows=[])

    mints = [row.mint_address for row in open_rows]
    # DISTINCT ON, not MAX. `MAX(price_usd)` grouped by mint returns the highest
    # price a token ever reached, which would value every open position at its
    # peak — the single most flattering bug this file could contain.
    latest = {
        mint: (price, at)
        for mint, price, at in await session.execute(
            select(
                TokenMarketSnapshot.mint_address,
                TokenMarketSnapshot.price_usd,
                TokenMarketSnapshot.captured_at,
            )
            .where(TokenMarketSnapshot.mint_address.in_(mints))
            .distinct(TokenMarketSnapshot.mint_address)
            .order_by(
                TokenMarketSnapshot.mint_address,
                TokenMarketSnapshot.captured_at.desc(),
            )
        )
    }

    now = datetime.now(UTC)
    rows: list[dict[str, object]] = []
    for row in open_rows[:SCREEN_ROWS]:
        price, observed = latest.get(row.mint_address, (None, None))
        age = (now - observed).total_seconds() if observed else None
        rows.append(
            {
                "mint": row.mint_address,
                "quantity": str(row.quantity),
                "entry_price": str(row.entry_price),
                "current_price": str(price) if price is not None else None,
                "multiple": str(price / row.entry_price)
                if price and row.entry_price
                else None,
                # The wallet's own stored target, not a recomputation of it. A
                # second multiplication here could disagree with the first.
                "target_price": str(row.target_price),
                "quote_age_seconds": age,
                "quote_stale": age is None or age > QUOTE_STALE_AFTER.total_seconds(),
            }
        )
    return Reading(
        measured=True,
        detail=f"{len(open_rows)} open, priced from the latest market snapshot per mint.",
        rows=rows,
    )


async def target_screen(session: AsyncSession, binding: Binding) -> Reading:
    """SCREEN 4 — what is closest to target, and what has already filled there.

    Sorted by distance to the wallet's published multiple rather than by size
    or age: the question this screen answers is "what is about to happen", and
    nothing else on it matters.
    """
    if not binding.readable:
        return _unavailable(binding)

    live = await positions_screen(session, binding)
    target = binding.take_profit_multiple or Decimal("1.25")
    approaching = sorted(
        (row for row in live.rows if row.get("multiple") is not None),
        key=lambda row: abs(Decimal(str(row["multiple"])) - target),
    )[:SCREEN_ROWS]

    hits = (
        await session.execute(
            select(func.count())
            .select_from(_POS)
            .where(_POS.c.wallet_id == binding.wallet_id, _POS.c.exit_reason == "target_1_25x")
        )
    ).scalar_one()

    return Reading(
        measured=True,
        detail=f"Target is {target}x from the entry reference price.",
        values={"target_multiple": str(target), "target_hits_lifetime": hits},
        rows=approaching,
    )


async def accounting(session: AsyncSession, binding: Binding) -> Reading:
    """§15's invariant: cash + executable open value ≈ equity.

    Reported as a *difference* with the inputs beside it rather than as a
    pass/fail. A boolean would hide the size of a mismatch, and the size is the
    thing that tells an owner whether they are looking at a rounding artefact
    or at a wallet that has lost track of its own money.
    """
    if not binding.readable:
        return _unavailable(binding)

    book = await wallet_screen(session, binding)
    live = await positions_screen(session, binding)

    priced = [row for row in live.rows if row.get("current_price") is not None]
    if len(priced) != len(live.rows):
        return Reading(
            measured=False,
            detail=(
                f"{len(live.rows) - len(priced)} of {len(live.rows)} open positions "
                "have no current price, so executable open value cannot be computed. "
                "Not reported as a mismatch — an unpriced book is unmeasured, not wrong."
            ),
        )

    cash = Decimal(str(book.values["cash_usd"]))
    open_value = sum(
        (Decimal(str(row["quantity"])) * Decimal(str(row["current_price"])) for row in priced),
        Decimal(0),
    )
    return Reading(
        measured=True,
        detail="cash + executable open value, against derived equity.",
        values={
            "cash_usd": str(cash),
            "open_value_usd": str(open_value),
            "equity_usd": str(cash + open_value),
        },
    )
