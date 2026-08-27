"""V5 Forward Strategy Arena: three tables. Additive only, research-only.

No production table is touched. The Arena cannot reach paper, karthik or
real-wallet accounting — by schema as well as by code.

Revision ID: 0048_forward_arena
Revises: 0047_quote_checkpoints
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0048_forward_arena"
down_revision = "0047_quote_checkpoints"
branch_labels = None
depends_on = None

MONEY = sa.Numeric(24, 4)
PRICE = sa.Numeric(38, 18)
QTY = sa.Numeric(48, 18)


def _pk():
    return sa.Column("id", postgresql.UUID(as_uuid=True),
                     server_default=sa.text("gen_random_uuid()"), nullable=False)


def _stamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "arena_candidates", _pk(),
        sa.Column("code", sa.String(2), nullable=False),
        sa.Column("name", sa.String(48), nullable=False),
        sa.Column("version", sa.String(16), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("starting_equity", MONEY, nullable=False),
        sa.Column("cash", MONEY, nullable=False),
        sa.Column("status", sa.String(12), server_default="active", nullable=False),
        sa.Column("failed_reason", sa.String(64), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("peak_equity", MONEY, nullable=False),
        *_stamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", "version", name="uq_arena_candidate_code_version"),
        sa.CheckConstraint("status IN ('active','failed')", name="ck_arena_candidate_status"),
    )
    op.create_index("ix_arena_candidates_created_at", "arena_candidates", ["created_at"])

    op.create_table(
        "arena_decisions", _pk(),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("arena_candidates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mint_address", sa.String(44), nullable=False),
        sa.Column("token_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("discovered_tokens.id", ondelete="CASCADE"), nullable=True),
        sa.Column("checkpoint_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checkpoint_minutes", sa.Integer(), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("skip_reason", sa.String(48), nullable=True),
        sa.Column("features", postgresql.JSONB(), nullable=True),
        sa.Column("route_state", sa.String(20), nullable=True),
        sa.Column("quoted_impact_pct", sa.Numeric(12, 6), nullable=True),
        *_stamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id", "mint_address", name="uq_arena_decision_once"),
        sa.CheckConstraint(
            "route_state IS NULL OR route_state IN "
            "('BUY_OK_SELL_OK','BUY_OK_SELL_FAILED','BUY_FAILED','ROUTE_UNKNOWN')",
            name="ck_arena_decision_route"),
    )
    op.create_index("ix_arena_decisions_candidate_checkpoint", "arena_decisions",
                    ["candidate_id", "checkpoint_at"])
    op.create_index("ix_arena_decisions_created_at", "arena_decisions", ["created_at"])

    op.create_table(
        "arena_positions", _pk(),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("arena_candidates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("arena_decisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mint_address", sa.String(44), nullable=False),
        sa.Column("token_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("discovered_tokens.id", ondelete="CASCADE"), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", PRICE, nullable=False),
        sa.Column("size_usd", MONEY, nullable=False),
        sa.Column("quantity", QTY, nullable=False),
        sa.Column("target_price", PRICE, nullable=False),
        sa.Column("entry_impact_pct", sa.Numeric(12, 6), nullable=True),
        sa.Column("entry_source", sa.String(16), nullable=False),
        sa.Column("status", sa.String(8), server_default="open", nullable=False),
        sa.Column("peak_multiple", sa.Numeric(20, 6), nullable=True),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_price", PRICE, nullable=True),
        sa.Column("exit_proceeds_usd", MONEY, nullable=True),
        sa.Column("exit_reason", sa.String(24), nullable=True),
        sa.Column("route_state", sa.String(20), nullable=True),
        sa.Column("reached_125", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("reached_150", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("reached_200", sa.Boolean(), server_default="false", nullable=False),
        *_stamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id", "mint_address", name="uq_arena_position_once"),
        sa.CheckConstraint("status IN ('open','closed')", name="ck_arena_position_status"),
    )
    op.create_index("ix_arena_positions_candidate_status", "arena_positions",
                    ["candidate_id", "status"])
    op.create_index("ix_arena_positions_created_at", "arena_positions", ["created_at"])


def downgrade() -> None:
    op.drop_table("arena_positions")
    op.drop_table("arena_decisions")
    op.drop_table("arena_candidates")
