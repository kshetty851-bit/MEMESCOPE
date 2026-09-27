"""Family members and their own-wallet settings.

USER 1 … USER 10 (the family wallets until 2026-09-27) each have a Solana
wallet of their own
(`app.real_wallet.family_wallets` pins whose key is whose). This table holds
whether each one trades and how much each trade spends.

It used to hold their SHARES of the owner's wallet too — a share switch and
size here, plus a ledger and per-order allocation tables. Those went on
2026-09-25 at Karthik's request, once the members had wallets of their own
(migration 0105).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
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
    #: The share of each month's NEW profit (above the high-water mark) this
    #: user pays Karthik. 0.20 by default; USER 1 pays none (Karthik,
    #: 2026-09-27). Shown on the user's own page.
    fee_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, default=Decimal("0.20"), server_default="0.20")


class RealWalletUserFee(Base):
    """One user wallet's fee for one calendar month (UTC), and its payment.

    `profit_usd` is the wallet's realised trading profit from its first trade
    to the end of `period` — deposits and withdrawals never move it. The fee is
    `fee_rate` of whatever that total gained above `hwm_before_usd`, the
    highest total any earlier month was charged at; `hwm_after_usd` is the new
    mark. A month that made nothing new is still a row, with status "none".

    status: none | due | sending | paid | uncertain. "sending" is written and
    committed BEFORE the transfer is submitted, so a crash mid-send leaves a
    row nobody retries; "uncertain" is a send whose answer was lost. Neither is
    ever sent again automatically — the chain decides what happened.
    """

    __tablename__ = "real_wallet_user_fees"
    __table_args__ = (
        UniqueConstraint("member", "period", name="uq_real_wallet_user_fee_month"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True,
                                          default=uuid.uuid4)
    member: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    wallet: Mapped[str] = mapped_column(String(64), nullable=False)
    period: Mapped[date] = mapped_column(Date, nullable=False)
    profit_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    hwm_before_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    hwm_after_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    fee_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    fee_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    sol_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    lamports: Mapped[int | None] = mapped_column(Numeric(20, 0))
    signature: Mapped[str | None] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
