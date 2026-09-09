"""Who bought a token FIRST, kept for the wallets rather than the token.

This is the raw material for a KOL lab built on what people DO rather than
what they say. The scanner already decodes the trader's wallet on every trade
— `TradeEvent.user`, from the bonding-curve log — and until now folded it
straight into aggregate counts and threw the address away. Nothing on this
platform could answer "which wallets are repeatedly early into coins that go
somewhere", because nothing remembered who anybody was.

## Why only the first few buyers, and only of some coins

Persisting every trade is not an option: the scanner sustains hundreds of
events a second, tens of millions a day. Two bounds make this cheap enough to
keep forever.

FIRST, only the earliest N distinct BUYERS of a mint are captured, in memory,
at first sight. Being early is the whole signal — a wallet that bought after
the crowd tells us nothing — so the tail is not merely expensive, it is
uninformative. The capture stops after N and costs nothing thereafter.

SECOND, they are only WRITTEN for coins that go on to matter. Capturing must
happen at the start and relevance is only known later, so the two are split:
memory holds the early buyers of every mint the scanner sees, and the flush
persists them only for mints that reached real liquidity. Coins that never
get there are evicted from memory unwritten and cost nothing on disk.

## What this deliberately is not

Not a P&L. It records that a wallet was among the first buyers, not what it
made — pump.fun's own leaderboard claimed $1M+ for wallets whose on-chain
realised SOL was NEGATIVE, and any ranking that trusts a reported profit
inherits that. What a wallet earned has to be derived from its own subsequent
trades, forward, not read off anybody's scoreboard.

Nor is it a point-in-time ranking on its own. `bought_at` is stored so that a
ranking can be built over one window and tested on a later one; scoring a
wallet on the same trades that selected it is the selection trap that has
produced four false edges here already.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TokenEarlyBuyer(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One wallet that was among the first buyers of one mint."""

    __tablename__ = "token_early_buyers"

    mint_address: Mapped[str] = mapped_column(String(64), nullable=False)
    wallet_address: Mapped[str] = mapped_column(String(64), nullable=False)

    #: When the scanner saw this wallet's first buy of this mint. The axis a
    #: forward test is split on, so it is the trade's own time and never the
    #: write time.
    bought_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    #: 1 for the first buyer seen, 2 for the second, and so on. Kept because
    #: "first in" and "twentieth in" are different claims about a wallet, and
    #: collapsing them would hide which one the data supports.
    buy_rank: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        # One row per wallet per mint. The flush is idempotent and may run
        # many times over the same mint's life; without this it would write a
        # duplicate on every pass and inflate any count taken over the table.
        UniqueConstraint("mint_address", "wallet_address",
                         name="uq_early_buyer_once"),
        # The ranking read: every mint one wallet was early into.
        Index("ix_early_buyer_wallet", "wallet_address", "bought_at"),
        # The per-token read, and the retention scan.
        Index("ix_early_buyer_mint", "mint_address"),
        Index("ix_early_buyer_at", "bought_at"),
    )
