"""Immutable forward Radar-quality research records.

These tables intentionally sit beside, rather than inside, ``radar_tokens``.
They observe a Radar evaluation after it commits and never participate in the
score, ranking, scanner, or selection paths.  A missing research write must
therefore cost research coverage only, never a market opportunity.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_SCORE = Numeric(7, 3)


class RadarDecisionSnapshot(Base):
    """One immutable, decision-time view of a meaningful Radar evaluation."""

    __tablename__ = "radar_decision_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    #: Deterministic UUID5 over mint, evaluated_at and exact market row.  It
    #: makes a technical retry a no-op while leaving a later evaluation distinct.
    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, unique=True
    )
    evaluation_key: Mapped[str] = mapped_column(String(180), nullable=False, unique=True)

    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)
    token_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("discovered_tokens.id", ondelete="SET NULL")
    )
    radar_token_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("radar_tokens.id", ondelete="SET NULL")
    )
    market_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("token_market_snapshots.id", ondelete="SET NULL")
    )

    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Kept distinct because ranking is read from the committed canonical board
    #: immediately after the Radar transaction; it is never reconstructed later.
    rank_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    time_since_discovery_seconds: Mapped[Decimal | None] = mapped_column(Numeric(20, 3))

    radar_rank: Mapped[int | None] = mapped_column(Integer)
    rank_state: Mapped[str] = mapped_column(String(32), nullable=False)
    radar_score: Mapped[Decimal | None] = mapped_column(_SCORE)
    confidence_score: Mapped[Decimal | None] = mapped_column(_SCORE)
    risk_score: Mapped[Decimal | None] = mapped_column(_SCORE)
    risk_band: Mapped[str] = mapped_column(String(32), nullable=False)
    eligibility_state: Mapped[str] = mapped_column(String(32), nullable=False)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False)

    selection_reasons: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    rejection_reasons: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    vetoes: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    why_now: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    radar_algorithm_version: Mapped[str] = mapped_column(String(64), nullable=False)
    radar_configuration_version: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)

    token_identity: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    component_state: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    market_state: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    derived_features: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    availability: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    provenance: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_radar_decision_snapshots_mint_evaluated", "mint_address", "evaluated_at"),
        Index("ix_radar_decision_snapshots_evaluated", "evaluated_at"),
        Index("ix_radar_decision_snapshots_rank", "radar_rank"),
        Index("ix_radar_decision_snapshots_selected", "selected", "evaluated_at"),
    )


class RadarRankEvent(Base):
    """Append-only rank transitions, including passive Top-20 moves."""

    __tablename__ = "radar_rank_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    event_key: Mapped[str] = mapped_column(String(180), nullable=False, unique=True)
    decision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("radar_decision_snapshots.id", ondelete="SET NULL")
    )
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)
    radar_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    rank_band: Mapped[str] = mapped_column(String(32), nullable=False)
    event_source: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_radar_rank_events_mint_observed", "mint_address", "observed_at"),
        Index("ix_radar_rank_events_rank_observed", "radar_rank", "observed_at"),
    )


class RadarDecisionOutcome(Base):
    """Append-only future labels; never an input to a Radar decision."""

    __tablename__ = "radar_decision_outcomes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("radar_decision_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    outcome_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    horizon: Mapped[str] = mapped_column(String(32), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    market_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("token_market_snapshots.id", ondelete="SET NULL")
    )
    reference_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    observed_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    future_multiple: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    availability: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    provenance: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "decision_id", "outcome_kind", "horizon", name="uq_radar_decision_outcome"
        ),
        Index("ix_radar_decision_outcomes_decision", "decision_id"),
        Index("ix_radar_decision_outcomes_due", "due_at"),
    )
