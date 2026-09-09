"""The wallets a KOL tournament decided to follow, frozen at its activation.

Stored rather than recomputed, and that is the whole point. A ranking that is
recalculated on every read would silently start including the very trades the
lab is making decisions about — the wallet that looks good today because the
coin it bought this morning ran this afternoon. Freezing it at `computed_at`
makes the tournament a forward test of one specific, dated claim.

`early_buys` and `hits` are kept beside the score so the claim can be judged
rather than taken: a 100% hit rate over five coins and one over forty are very
different statements, and a score alone hides which one you are looking at.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class KolWalletRank(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One wallet a tournament follows, with the evidence that selected it."""

    __tablename__ = "kol_wallet_ranks"

    #: Which tournament's frozen view this belongs to.
    spec_version: Mapped[str] = mapped_column(String(16), nullable=False)

    #: The instant the ranking was taken. Nothing after it was read.
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    wallet_address: Mapped[str] = mapped_column(String(64), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)

    #: The evidence, kept so the score can be argued with.
    early_buys: Mapped[int] = mapped_column(Integer, nullable=False)
    hits: Mapped[int] = mapped_column(Integer, nullable=False)
    hit_rate: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("spec_version", "wallet_address",
                         name="uq_kol_rank_once"),
        Index("ix_kol_rank_lookup", "spec_version", "wallet_address"),
    )
