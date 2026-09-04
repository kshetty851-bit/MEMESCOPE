"""Every leader trade we saw, and what we did about it.

The audit trail the copy lab rests on. One row per leader transaction, whether
or not we acted, because the SKIPS are the evidence: a copier that only records
its own fills cannot answer the question that decides whether copying works —
how much of what he did were we able to do.

`leader_at` and `seen_at` are both stored so the LAG is measurable rather than
assumed. He holds a median of 8.5 minutes; if we are routinely four minutes
behind him, the copy is a different trade from his and the ledger says so in
seconds rather than in argument.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.lab import MONEY


class PumpfunSignal(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One observed trade by the wallet being mirrored."""

    __tablename__ = "pumpfun_signals"

    tournament_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("lab_tournaments.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: The leader's transaction. UNIQUE — this is what stops one trade being
    #: copied twice when polls overlap, and it is a database constraint rather
    #: than a check in the tick because the tick can run concurrently.
    signature: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)
    mint_address: Mapped[str] = mapped_column(String(64), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    #: What HE staked. Recorded for context only — we size from our own book.
    leader_sol: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)

    leader_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    acted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    #: `opened`, `closed`, or the reason we did not act: `before_watch_start`,
    #: `stale_signal`, `already_held`, `not_held`, `max_concurrent`,
    #: `insufficient_cash`, `unpriceable`.
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    position_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("lab_positions.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_pumpfun_signal_seen", "tournament_id", "seen_at"),
        Index("ix_pumpfun_signal_mint", "mint_address"),
    )
