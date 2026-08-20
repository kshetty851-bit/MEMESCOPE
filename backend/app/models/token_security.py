"""Append-only shared token-security evidence.

A separate table from `real_wallet_safety_evaluations` on purpose, and the
reason is semantic rather than tidiness. That table's `decision` column holds
ALLOW or REJECT and its `trade_size_usd` is NOT NULL, because a real-wallet
policy decision is only meaningful for a specific order size. This contract
has three states and no trade size. Writing an UNKNOWN verdict into a column
whose readers assume two values would corrupt an existing audit surface that
real-wallet execution intents hold foreign keys into.

Rows are historical evidence and are never updated in place: "what did the
platform know about this mint at that instant" has to keep its answer after
the token's security state has moved on.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class TokenSecurityEvaluationRow(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "token_security_evaluations"

    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    #: VERIFIED | FAILED | UNKNOWN. Never a boolean — see `security.contract`.
    overall_status: Mapped[str] = mapped_column(String(16), nullable=False)
    evaluator_version: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    #: The full per-check breakdown, so a stored verdict can be re-argued
    #: without re-running the RPC that produced it.
    checks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    #: When the market reading behind the venue checks was captured. Null when
    #: there was none — distinct from "captured at an unknown time".
    market_snapshot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_token_security_mint_evaluated_desc", "mint_address", evaluated_at.desc()),
        Index("ix_token_security_evaluated_at", "evaluated_at"),
        Index("ix_token_security_status", "overall_status"),
    )
