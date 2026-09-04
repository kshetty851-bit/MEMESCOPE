"""The Compound Lab's cycle ledger.

Positions, strategies and equity marks all live in the Lab's own tables — the
Compound Lab runs on the same engine over a different registry, so it gets a
`lab_tournaments` row of its own and nothing is duplicated. The ONE thing the
Lab has no concept of is a wallet-level target, and that is what this records.

One row per cycle. A cycle opens with a base and a target, and closes when
equity reaches the target and every position has been sold. `realised_equity`
is what the wallet actually banked, which is NOT the target: closing a book
pays impact, so a cycle that trips at $110.40 on marks may realise $109.80.
The next cycle compounds from what was realised, never from what was aimed at
— compounding from the target would invent money on every cycle and the error
would grow with each one.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.lab import MONEY


class CompoundCycle(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One run from a base to its +10% target, and what it actually banked."""

    __tablename__ = "compound_cycles"

    tournament_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("lab_tournaments.id", ondelete="CASCADE"),
        nullable=False,
    )
    strategy_row_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("lab_strategies.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: 1-based. Cycle 1 starts at the registry's starting equity.
    cycle_no: Mapped[int] = mapped_column(Integer, nullable=False)
    base_usd: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    target_usd: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: Null while the cycle is running.
    reached_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Equity on MARKS at the moment the target tripped — what was aimed at.
    equity_at_target: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    #: Equity after every position was actually sold — what was banked, and the
    #: base of the next cycle. Lower than `equity_at_target` by the impact of
    #: closing the book.
    realised_equity: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    positions_closed: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    #: Why the cycle ended: `target_reached`, or `floor` when the wallet fell
    #: through the failure floor and stopped.
    outcome: Mapped[str | None] = mapped_column(String(24), nullable=True)

    __table_args__ = (
        Index("ix_compound_cycle_no", "strategy_row_id", "cycle_no", unique=True),
        Index("ix_compound_cycle_open", "strategy_row_id", "reached_at"),
    )
