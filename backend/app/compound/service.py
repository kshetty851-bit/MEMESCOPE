"""The Compound Lab: trade a rule, take profit on the WALLET, compound.

The engine is the Lab's — same execution model, same marking, same stale guard
and glitch band, same accounting — handed a different frozen registry. What
lives here is the one thing the Lab has no concept of: a target on total
equity rather than on a position.

## The cycle

A cycle opens with a `base` and a `target` of `base x 1.10`. The wallet trades
its rule. When equity reaches the target, every open position is sold and the
cycle closes. The next cycle's base is what was ACTUALLY REALISED, never the
target — closing a book pays impact, so a cycle that trips at $110.40 on marks
may bank $109.80, and compounding from the target instead would invent the
difference on every cycle and grow the error with each one.

## Why the target is checked on executable equity

`LabService.equity` is cash plus what the open book could be SOLD for, not
plus what it cost. A target measured on cost would fire on a wallet that could
not actually realise it, and the sale immediately afterwards would prove it —
the cycle would close below its own target, every time.

## What it refuses to do

It does not open a new cycle while positions are still open. Selling the book
is part of closing a cycle, and a base counted while the previous cycle's
positions were still live would count that capital twice.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.compound import spec as cspec
from app.core.logging import get_logger
from app.lab.service import LabService
from app.models.compound import CompoundCycle
from app.models.lab import LabPosition, LabStrategy, LabTournament

logger = get_logger(__name__)

#: How a position that left the book because the WALLET hit its target is
#: recorded. Distinct from `manual_close` (a person) and from every rule-driven
#: exit (the position's own target or clock).
CYCLE_EXIT_REASON = "cycle_target"


class CompoundService:
    def __init__(self, session) -> None:
        self._session = session
        self._lab = LabService(session, registry=cspec)

    async def _row(self) -> tuple[LabTournament, LabStrategy] | None:
        t = (await self._session.execute(
            select(LabTournament).where(
                LabTournament.spec_version == cspec.SPEC_VERSION)
        )).scalars().first()
        if t is None:
            return None
        row = (await self._session.execute(
            select(LabStrategy).where(LabStrategy.tournament_id == t.id)
        )).scalars().first()
        return None if row is None else (t, row)

    async def _open_cycle(self, t, row, *, now: datetime) -> CompoundCycle:
        """The running cycle, opening the first one if there is none."""
        cycle = (await self._session.execute(
            select(CompoundCycle)
            .where(CompoundCycle.strategy_row_id == row.id,
                   CompoundCycle.reached_at.is_(None))
            .order_by(CompoundCycle.cycle_no.desc())
        )).scalars().first()
        if cycle is not None:
            return cycle

        last = (await self._session.execute(
            select(CompoundCycle)
            .where(CompoundCycle.strategy_row_id == row.id)
            .order_by(CompoundCycle.cycle_no.desc())
        )).scalars().first()
        # The first cycle starts at the registry's book. Every later one starts
        # at what the previous cycle actually banked.
        base = (last.realised_equity if last is not None
                else cspec.STARTING_EQUITY)
        cycle = CompoundCycle(
            tournament_id=t.id, strategy_row_id=row.id,
            cycle_no=(last.cycle_no + 1) if last else 1,
            base_usd=base, target_usd=base * cspec.CYCLE_TARGET_MULTIPLE,
            started_at=now,
        )
        self._session.add(cycle)
        await self._session.flush()
        logger.info("compound_cycle_opened", cycle=cycle.cycle_no,
                    base=str(cycle.base_usd), target=str(cycle.target_usd))
        return cycle

    async def _sell_the_book(self, row, *, now: datetime) -> int:
        """Close every open position through the ordinary fill path.

        Not a special case: it calls the same close the sell button does, with
        its own reason. A cycle that banked its profit at prices the market
        would not have paid would compound a number that never existed.
        """
        opens = list((await self._session.execute(
            select(LabPosition).where(LabPosition.strategy_row_id == row.id,
                                      LabPosition.status == "open")
        )).scalars())
        closed = 0
        for pos in opens:
            out = await self._lab.close_manually(
                position_id=pos.id, now=now, actor="compound_cycle",
                reason=CYCLE_EXIT_REASON,
            )
            if out.get("closed"):
                closed += 1
        return closed

    async def tick(self, *, now: datetime) -> dict[str, Any]:
        """One pass: judge, settle, then test the wallet against its target."""
        t = await self._lab.activate(valid_from=now)
        found = await self._row()
        if found is None:
            return {"skipped": "not_activated"}
        _t, row = found

        cycle = await self._open_cycle(t, row, now=now)
        decided = await self._lab.evaluate_due(now=now)
        settled = await self._lab.settle(now=now)
        await self._lab.record_equity(now=now)

        equity = await self._lab.equity(row)
        if equity < cycle.target_usd:
            return {"cycle": cycle.cycle_no, "base": str(cycle.base_usd),
                    "target": str(cycle.target_usd), "equity": str(equity),
                    "decided": decided, "settled": settled, "banked": False}

        # Target reached. Sell everything, then bank what actually came back.
        closed = await self._sell_the_book(row, now=now)
        realised = await self._lab.equity(row)
        cycle.reached_at = now
        cycle.equity_at_target = equity
        cycle.realised_equity = realised
        cycle.positions_closed = closed
        cycle.outcome = "target_reached"
        await self._session.flush()
        logger.info("compound_cycle_banked", cycle=cycle.cycle_no,
                    at_target=str(equity), realised=str(realised),
                    closed=closed)

        nxt = await self._open_cycle(t, row, now=now)
        return {"cycle": cycle.cycle_no, "banked": True,
                "equity_at_target": str(equity), "realised": str(realised),
                "positions_closed": closed,
                "next_cycle": nxt.cycle_no, "next_target": str(nxt.target_usd),
                "decided": decided, "settled": settled}
