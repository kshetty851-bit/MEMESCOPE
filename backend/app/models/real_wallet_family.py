"""Family members and their own-wallet settings.

Jaya, Asha and Apoorva each have a Solana wallet of their own
(`app.real_wallet.family_wallets` pins whose key is whose). This table holds
whether each one trades and how much each trade spends.

It used to hold their SHARES of the owner's wallet too — a share switch and
size here, plus a ledger and per-order allocation tables. Those went on
2026-09-25 at Karthik's request, once the members had wallets of their own
(migration 0105).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RealWalletFamilyMember(Base):
    __tablename__ = "real_wallet_family_members"

    name: Mapped[str] = mapped_column(String(16), primary_key=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_by: Mapped[str | None] = mapped_column(String(120))
    # Off until Karthik, signed in, switches it on
    # (`family_api.member_own_settings`); anyone with the family password may
    # switch it off.
    own_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false")
    own_ticket_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("20"), server_default="20")
    own_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    own_updated_by: Mapped[str | None] = mapped_column(String(120))
