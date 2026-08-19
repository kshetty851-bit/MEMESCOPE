"""Forward-only immutable Radar-quality dataset.

Revision ID: 0028_radar_forward_quality
Revises: 0027_paper_research_ledger

The new tables are additive and have no triggers, foreign-key cascades, or
dependencies from the scanner/Radar write paths.  They are research evidence,
not ranking inputs.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0028_radar_forward_quality"
down_revision = "0027_paper_research_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "radar_decision_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("evaluation_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("evaluation_key", sa.String(180), nullable=False, unique=True),
        sa.Column("mint_address", sa.String(44), nullable=False),
        sa.Column("token_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("discovered_tokens.id", ondelete="SET NULL")),
        sa.Column("radar_token_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("radar_tokens.id", ondelete="SET NULL")),
        sa.Column("market_snapshot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("token_market_snapshots.id", ondelete="SET NULL")),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rank_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_discovered_at", sa.DateTime(timezone=True)),
        sa.Column("time_since_discovery_seconds", sa.Numeric(20, 3)),
        sa.Column("radar_rank", sa.Integer()),
        sa.Column("rank_state", sa.String(32), nullable=False),
        sa.Column("radar_score", sa.Numeric(7, 3)),
        sa.Column("confidence_score", sa.Numeric(7, 3)),
        sa.Column("risk_score", sa.Numeric(7, 3)),
        sa.Column("risk_band", sa.String(32), nullable=False),
        sa.Column("eligibility_state", sa.String(32), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False),
        sa.Column("selection_reasons", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("rejection_reasons", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("vetoes", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("evidence", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("why_now", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("radar_algorithm_version", sa.String(64), nullable=False),
        sa.Column("radar_configuration_version", sa.String(64), nullable=False),
        sa.Column("feature_schema_version", sa.String(64), nullable=False),
        sa.Column("token_identity", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("component_state", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("market_state", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("derived_features", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("availability", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("provenance", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_radar_decision_snapshots_mint_evaluated", "radar_decision_snapshots", ["mint_address", "evaluated_at"])
    op.create_index("ix_radar_decision_snapshots_evaluated", "radar_decision_snapshots", ["evaluated_at"])
    op.create_index("ix_radar_decision_snapshots_rank", "radar_decision_snapshots", ["radar_rank"])
    op.create_index("ix_radar_decision_snapshots_selected", "radar_decision_snapshots", ["selected", "evaluated_at"])

    op.create_table(
        "radar_rank_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("event_key", sa.String(180), nullable=False, unique=True),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("radar_decision_snapshots.id", ondelete="SET NULL")),
        sa.Column("mint_address", sa.String(44), nullable=False),
        sa.Column("radar_rank", sa.Integer(), nullable=False),
        sa.Column("rank_band", sa.String(32), nullable=False),
        sa.Column("event_source", sa.String(32), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_radar_rank_events_mint_observed", "radar_rank_events", ["mint_address", "observed_at"])
    op.create_index("ix_radar_rank_events_rank_observed", "radar_rank_events", ["radar_rank", "observed_at"])

    op.create_table(
        "radar_decision_outcomes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("radar_decision_snapshots.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("outcome_kind", sa.String(32), nullable=False),
        sa.Column("horizon", sa.String(32), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("market_snapshot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("token_market_snapshots.id", ondelete="SET NULL")),
        sa.Column("reference_price", sa.Numeric(38, 18)),
        sa.Column("observed_price", sa.Numeric(38, 18)),
        sa.Column("future_multiple", sa.Numeric(24, 8)),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("availability", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("provenance", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("decision_id", "outcome_kind", "horizon", name="uq_radar_decision_outcome"),
    )
    op.create_index("ix_radar_decision_outcomes_decision", "radar_decision_outcomes", ["decision_id"])
    op.create_index("ix_radar_decision_outcomes_due", "radar_decision_outcomes", ["due_at"])


def downgrade() -> None:
    op.drop_table("radar_decision_outcomes")
    op.drop_table("radar_rank_events")
    op.drop_table("radar_decision_snapshots")
