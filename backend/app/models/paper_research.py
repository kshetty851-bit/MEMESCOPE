"""Immutable forward research records, deliberately outside paper accounting."""
# ruff: noqa: E501
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PaperDecisionSnapshot(Base):
    __tablename__ = "paper_decision_snapshots"
    __table_args__ = (
        UniqueConstraint("decision_source", "source_decision_key", name="uq_paper_decision_snapshot_source"),
        Index("ix_paper_decision_snapshot_decided", "decided_at"),
        Index("ix_paper_decision_snapshot_mint", "mint_address"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    decision_source: Mapped[str] = mapped_column(String(16), nullable=False)
    source_decision_key: Mapped[str] = mapped_column(String(128), nullable=False)
    wallet_code: Mapped[str] = mapped_column(String(32), nullable=False)
    strategy_id: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    mint_address: Mapped[str] = mapped_column(String(44), nullable=False)
    token_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("discovered_tokens.id", ondelete="SET NULL"))
    market_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("token_market_snapshots.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    feature_schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="decision_feature_schema_v1")
    market_features: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    radar_state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    observation_history: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    availability: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PaperDecisionEnrichment(Base):
    __tablename__ = "paper_decision_enrichments"
    __table_args__ = (Index("ix_paper_decision_enrichment_decision", "decision_id"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    decision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("paper_decision_snapshots.id", ondelete="RESTRICT"), nullable=False)
    enrichment_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PaperDecisionOutcome(Base):
    __tablename__ = "paper_decision_outcomes"
    __table_args__ = (Index("ix_paper_decision_outcome_decision", "decision_id"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    decision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("paper_decision_snapshots.id", ondelete="RESTRICT"), nullable=False)
    horizon: Mapped[str] = mapped_column(String(32), nullable=False)
    market_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("token_market_snapshots.id", ondelete="SET NULL"))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
