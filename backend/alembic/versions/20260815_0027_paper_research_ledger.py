"""Forward-only immutable paper decision research ledger.

Revision ID: 0027_paper_research_ledger
Revises: 0026_report_deliveries
"""
from __future__ import annotations
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0027_paper_research_ledger"
down_revision = "0026_report_deliveries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("paper_decision_snapshots", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")), sa.Column("decision_source", sa.String(16), nullable=False), sa.Column("source_decision_key", sa.String(128), nullable=False), sa.Column("wallet_code", sa.String(32), nullable=False), sa.Column("strategy_id", sa.String(64), nullable=False), sa.Column("strategy_version", sa.String(32), nullable=False), sa.Column("mint_address", sa.String(44), nullable=False), sa.Column("token_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("discovered_tokens.id", ondelete="SET NULL")), sa.Column("market_snapshot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("token_market_snapshots.id", ondelete="SET NULL")), sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False), sa.Column("decision", sa.String(16), nullable=False), sa.Column("reason_codes", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")), sa.Column("feature_schema_version", sa.String(32), nullable=False, server_default="decision_feature_schema_v1"), sa.Column("market_features", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("radar_state", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("observation_history", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("availability", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")), sa.UniqueConstraint("decision_source", "source_decision_key", name="uq_paper_decision_snapshot_source"))
    op.create_index("ix_paper_decision_snapshot_decided", "paper_decision_snapshots", ["decided_at"]); op.create_index("ix_paper_decision_snapshot_mint", "paper_decision_snapshots", ["mint_address"])
    for table, extra in (("paper_decision_enrichments", "enrichment_type"), ("paper_decision_outcomes", "horizon")):
        op.create_table(table, sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")), sa.Column("decision_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("paper_decision_snapshots.id", ondelete="RESTRICT"), nullable=False), sa.Column(extra, sa.String(64 if extra == "enrichment_type" else 32), nullable=False), sa.Column("market_snapshot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("token_market_snapshots.id", ondelete="SET NULL"), nullable=True) if table.endswith("outcomes") else sa.Column("source", sa.String(64), nullable=False), sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False), sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("provenance", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))
        op.create_index(f"ix_{table[:-1]}_decision", table, ["decision_id"])
def downgrade() -> None:
    op.drop_table("paper_decision_outcomes"); op.drop_table("paper_decision_enrichments"); op.drop_table("paper_decision_snapshots")
