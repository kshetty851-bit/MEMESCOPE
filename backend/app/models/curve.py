"""Bonding curve observations.

One table, append-only, mirroring the discipline `token_market_snapshots`
already holds: every read inserts a row and nothing is ever updated. That is
what makes curve progress a *series* rather than a current value, and a series
is what the near-graduation provider needs to tell a curve that is filling from
one parked at the same level.

**Only raw account fields are stored.** Progress is derived — see
`services/curve/state.py` — because a derived column is one that can drift from
its source, and because the derivation may need correcting once the layout is
confirmed against a live account.

`NUMERIC(20, 0)` rather than `BIGINT`: these are unsigned 64-bit on-chain
values and `u64` runs to 18,446,744,073,709,551,615, which overflows a signed
`bigint`. Today's values fit comfortably; the type is chosen so a protocol
change cannot silently corrupt a row.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin

#: An unsigned 64-bit integer, exactly.
_U64 = Numeric(20, 0)


class TokenCurveSnapshot(Base, UUIDPrimaryKeyMixin):
    """One read of a token's bonding curve account. Append-only."""

    __tablename__ = "token_curve_snapshots"

    token_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("discovered_tokens.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: Denormalised, so a token's curve history needs no join — the same reason
    #: `token_market_snapshots` carries it.
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)

    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # --- Raw account fields ---------------------------------------------------
    virtual_token_reserves: Mapped[Decimal] = mapped_column(_U64, nullable=False)
    virtual_sol_reserves: Mapped[Decimal] = mapped_column(_U64, nullable=False)
    real_token_reserves: Mapped[Decimal] = mapped_column(_U64, nullable=False)
    real_sol_reserves: Mapped[Decimal] = mapped_column(_U64, nullable=False)
    token_total_supply: Mapped[Decimal] = mapped_column(_U64, nullable=False)
    #: True once the curve has filled and the token has migrated. The one field
    #: that states graduation as a fact rather than inferring it from a venue.
    complete: Mapped[bool] = mapped_column(Boolean, nullable=False)

    __table_args__ = (
        # The dominant read: "this token's curve history, newest first".
        Index("ix_curve_snapshots_mint_captured", "mint_address", captured_at.desc()),
        # And the collector's own: "which curves completed recently".
        Index(
            "ix_curve_snapshots_complete",
            captured_at.desc(),
            # `text` rather than the mapped column: autogenerate cannot
            # serialise a MappedColumn into a migration predicate, and emits a
            # repr that will not import.
            postgresql_where=text("complete"),
        ),
        # The curve account changes on-chain, not on our clock. Two reads in the
        # same second would record one state twice and inflate a series the
        # provider reads as movement.
        UniqueConstraint(
            "mint_address", "captured_at", name="uq_curve_snapshots_mint_captured"
        ),
    )
