"""How the execution wallet is divided between strategies.

## What an allocation is, and what it is not

It is a share of the book: strategy V6-06 may deploy at most 40% of equity.
It is NOT permission to trade, and it is NOT a size. Every server-owned bound
in `AutonomousExecutionPolicy` — max trade, max open positions, total exposure,
daily notional, daily loss — remains global and is evaluated unchanged on top
of this. A strategy holding 100% is permitted exactly the same order as one
holding 10%; it simply has one fewer limit binding first.

That direction matters. An allocation can only ever *narrow* what a strategy
may do. If it could widen anything, dividing the wallet would be a way to
enlarge it, and the caps that exist to bound a mistake would be negotiable.

## Why fractions rather than dollars

A dollar allocation is correct on the day it is written and wrong afterwards:
the wallet grows, takes a fill, or the SOL price moves, and nobody re-runs the
arithmetic. An allocation that drifts out of date over-commits the book without
anybody editing it. A fraction is correct at every balance, unmaintained.

## Why the sum lives here and not in the database

The invariant is "enabled fractions sum to at most 1", which spans rows. A
row-level CHECK cannot see the other rows, and a trigger would put a second
authority on the same rule. So the database enforces the part it can see —
`0 < fraction <= 1`, refused regardless of which code path writes it — and this
service owns the part it cannot. Anything writing `real_wallet_allocations`
outside this service can over-commit the book, which is why nothing else does.

## The single-strategy fallback

With no enabled rows, this returns the autotrade switch's `nominated_strategy`
at fraction 1. That is not a default anybody chose; it is the behaviour the
wallet already had, preserved exactly, so that adding this table changes
nothing until an operator deliberately writes to it. A migration that silently
altered how a funded wallet sizes its orders would be the worst possible way to
ship this.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.real_wallet_execution import RealWalletAllocation
from app.real_wallet.autotrade import AutotradeSwitchService

#: The whole book. Enabled fractions may sum to this and no more.
FULL_BOOK = Decimal(1)


class OverCommittedError(ValueError):
    """Raised when enabling a fraction would take the enabled sum past 1.

    A refusal rather than a clamp. Silently reducing somebody's requested
    fraction to make it fit would leave the operator believing they had
    allocated a share they do not have.
    """


@dataclass(frozen=True, slots=True)
class Allocation:
    strategy_id: str
    fraction: Decimal
    #: True when this came from the fallback rather than a stored row, so a
    #: caller can tell "the operator divided the book" from "the operator never
    #: did, and this is the old single-strategy behaviour".
    implicit: bool = False

    def as_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "fraction": str(self.fraction),
            "implicit": self.implicit,
        }


class AllocationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def rows(self) -> list[RealWalletAllocation]:
        """Every allocation, enabled or not. Disabled rows are kept as evidence
        that a strategy was once funded, the same way an archived wallet is."""
        result = await self._session.scalars(
            select(RealWalletAllocation).order_by(RealWalletAllocation.strategy_id)
        )
        return list(result.all())

    async def enabled(self) -> list[Allocation]:
        """The strategies that may trade, and each one's share.

        Falls back to the nominated single strategy when nobody has divided the
        book — see the module docstring for why that fallback exists.
        """
        rows = await self._session.scalars(
            select(RealWalletAllocation)
            .where(RealWalletAllocation.enabled.is_(True))
            .order_by(RealWalletAllocation.strategy_id)
        )
        stored = [
            Allocation(strategy_id=r.strategy_id, fraction=Decimal(r.fraction))
            for r in rows.all()
        ]
        if stored:
            return stored

        switch = await AutotradeSwitchService(self._session).state()
        if not switch.nominated_strategy:
            return []
        return [
            Allocation(
                strategy_id=switch.nominated_strategy,
                fraction=FULL_BOOK,
                implicit=True,
            )
        ]

    async def committed(self, *, excluding: str | None = None) -> Decimal:
        """Sum of enabled fractions, optionally ignoring one strategy.

        `excluding` is what makes editing an existing allocation possible:
        raising V6-06 from 0.2 to 0.3 must compare against the OTHER strategies'
        total, not against a total that still counts V6-06's old 0.2.
        """
        rows = await self._session.scalars(
            select(RealWalletAllocation).where(RealWalletAllocation.enabled.is_(True))
        )
        return sum(
            (
                Decimal(r.fraction)
                for r in rows.all()
                if excluding is None or r.strategy_id != excluding
            ),
            Decimal(0),
        )

    async def set(
        self,
        *,
        strategy_id: str,
        fraction: Decimal,
        enabled: bool = True,
        note: str | None = None,
    ) -> RealWalletAllocation:
        """Create or update one strategy's share.

        Refuses rather than clamps when the book would be over-committed, and
        refuses a fraction outside (0, 1] before the database has to — the same
        rule stated in both places on purpose, because the database's copy is
        what holds when something writes around this service.
        """
        strategy_id = strategy_id.upper().strip()
        if not strategy_id:
            raise ValueError("strategy_id is required")
        if fraction <= 0 or fraction > FULL_BOOK:
            raise ValueError(f"fraction must be within (0, 1]; got {fraction}")

        if enabled:
            others = await self.committed(excluding=strategy_id)
            if others + fraction > FULL_BOOK:
                raise OverCommittedError(
                    f"{strategy_id} at {fraction} would take the book to "
                    f"{others + fraction}; {FULL_BOOK - others} is unallocated"
                )

        row = await self._session.scalar(
            select(RealWalletAllocation).where(
                RealWalletAllocation.strategy_id == strategy_id
            )
        )
        if row is None:
            row = RealWalletAllocation(strategy_id=strategy_id)
            self._session.add(row)
        row.fraction = fraction
        row.enabled = enabled
        if note is not None:
            row.note = note
        await self._session.flush()
        return row

    async def disable(self, *, strategy_id: str) -> RealWalletAllocation | None:
        """Stop a strategy trading without forgetting it was funded.

        Deliberately not a delete. The row is the record that this strategy held
        a share of real capital, and that stays true after it stops.
        """
        strategy_id = strategy_id.upper().strip()
        row = await self._session.scalar(
            select(RealWalletAllocation).where(
                RealWalletAllocation.strategy_id == strategy_id
            )
        )
        if row is None:
            return None
        row.enabled = False
        await self._session.flush()
        return row
