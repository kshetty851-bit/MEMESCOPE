"""Family shares of the one real wallet.

Jaya, Asha and Apoorva do not have wallets of their own. The real wallet is
still ONE address, signed for by one isolated signer, and it still places one
order per coin. Each family member owns a slice of those orders: their own
trade size, their own on/off, and their own money, recorded here because on
chain every dollar arrives from, and leaves to, the owner's single address.

Three tables, nothing else changes shape:

* `real_wallet_family_members` - who takes part and at what size.
* `real_wallet_family_ledger` - money the owner has put in or taken out on a
  member's behalf. Recorded by hand, because the chain cannot tell a deposit
  for Jaya from one for Asha.
* `real_wallet_family_allocations` - each member's dollars inside one BUY
  intent, written in the same transaction as the intent. A member's profit on
  a trade is that share of the position's realised result.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RealWalletFamilyMember(Base):
    __tablename__ = "real_wallet_family_members"

    name: Mapped[str] = mapped_column(String(16), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ticket_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_by: Mapped[str | None] = mapped_column(String(120))


class RealWalletFamilyLedger(Base):
    __tablename__ = "real_wallet_family_ledger"
    __table_args__ = (
        CheckConstraint("kind in ('deposit', 'withdrawal')",
                        name="ck_real_wallet_family_ledger_kind"),
        CheckConstraint("amount_usd > 0", name="ck_real_wallet_family_ledger_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    member: Mapped[str] = mapped_column(
        String(16), ForeignKey("real_wallet_family_members.name"), nullable=False,
        index=True)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)  # deposit | withdrawal
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    note: Mapped[str | None] = mapped_column(String(200))
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    actor: Mapped[str | None] = mapped_column(String(120))


class RealWalletFamilyAllocation(Base):
    __tablename__ = "real_wallet_family_allocations"
    __table_args__ = (
        CheckConstraint("amount_usd > 0", name="ck_real_wallet_family_alloc_positive"),
    )

    intent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("real_wallet_live_intents.id"), primary_key=True)
    member: Mapped[str] = mapped_column(
        String(16), ForeignKey("real_wallet_family_members.name"), primary_key=True)
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
