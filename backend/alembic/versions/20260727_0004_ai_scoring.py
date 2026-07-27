"""Add AI scoring tables

Revision ID: 0004_ai_scoring
Revises: 0003_market_enrichment
Create Date: 2026-07-27

Phase 1 of the AI Scoring Engine (docs/AI_SCORING_DESIGN.md §11). Purely
additive: two new tables and one new enum type. No existing table is altered, so
this is reversible and can ship ahead of the engine that fills it.

Deliberately absent: any foreign key into `token_market_snapshots`. Provenance
is carried as a timestamp instead, because an enforced FK would block the
partition detach/drop that snapshot retention will eventually need.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_ai_scoring"
down_revision: str | None = "0003_market_enrichment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Scores are bounded 0.00-100.00. Numeric, not float, so values round-trip
# exactly and golden-file comparisons stay meaningful.
SCORE = sa.Numeric(5, 2)

# Mirrors RANKING_HOT_MIN_EVIDENCE in app/models/score.py and the `min_evidence`
# default on the ranking endpoint. All three move together.
RANKING_HOT_MIN_EVIDENCE = 25

_SCORE_COLUMNS = ("score", "evidence", "coverage", "market_risk", "opportunity_raw")


def _bounds() -> list[sa.CheckConstraint]:
    """0-100 guards, plus a non-negative observation count.

    Names are unprefixed: the metadata naming convention
    (`ck_%(table_name)s_%(constraint_name)s`) adds the prefix, so spelling it
    here would produce `ck_token_scores_ck_token_scores_score_range` and diverge
    from what the models create.
    """
    checks = [
        sa.CheckConstraint(f"{column} >= 0 AND {column} <= 100", name=f"{column}_range")
        for column in _SCORE_COLUMNS
    ]
    checks.append(
        sa.CheckConstraint("observations >= 0", name="observations_non_negative")
    )
    return checks


def _shared_columns() -> list[sa.Column]:
    """Columns common to the current-score and history tables."""
    return [
        sa.Column("token_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mint_address", sa.String(length=44), nullable=False),
        sa.Column("model_version", sa.String(length=32), nullable=False),
        sa.Column("score", SCORE, nullable=False),
        sa.Column("evidence", SCORE, nullable=False),
        sa.Column("coverage", SCORE, nullable=False),
        sa.Column("market_risk", SCORE, nullable=False),
        sa.Column("opportunity_raw", SCORE, nullable=False),
        sa.Column("observations", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_elite", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("has_veto", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("latest_snapshot_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "source_snapshot_captured_at", sa.DateTime(timezone=True), nullable=True
        ),
    ]


def upgrade() -> None:
    score_grade = postgresql.ENUM(
        "critical",
        "weak",
        "watch",
        "strong",
        "high_conviction",
        name="score_grade",
        create_type=False,
    )
    score_grade.create(op.get_bind(), checkfirst=True)

    # --- Current score: one mutable row per token ----------------------------
    # Narrow on purpose. This row is rewritten on every evaluation, so the
    # per-component JSONB lives in the history table instead; keeping it here
    # would mean rewriting kilobytes per token per refresh.
    op.create_table(
        "token_scores",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        *_shared_columns(),
        sa.Column("grade", score_grade, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_token_scores"),
        sa.ForeignKeyConstraint(
            ["token_id"],
            ["discovered_tokens.id"],
            name="fk_token_scores_token_id_discovered_tokens",
            ondelete="CASCADE",
        ),
        # Required by the ON CONFLICT (token_id) upsert, not merely a data rule.
        sa.UniqueConstraint("token_id", name="uq_token_scores_token_id"),
        *_bounds(),
    )
    op.create_index(
        "ix_token_scores_mint_address", "token_scores", ["mint_address"], unique=True
    )
    op.create_index("ix_token_scores_created_at", "token_scores", ["created_at"])

    # Keyset ranking within one model version: ORDER BY score DESC, mint ASC.
    # The tiebreak column is in the index so cursor paging is a range scan.
    op.create_index(
        "ix_token_scores_ranking",
        "token_scores",
        ["model_version", sa.text("score DESC"), "mint_address"],
    )
    # The default filter set gets a partial index; vetoed and low-evidence rows
    # are the bulk of the table and never appear in the common ranking.
    op.create_index(
        "ix_token_scores_ranking_hot",
        "token_scores",
        ["model_version", sa.text("score DESC"), "mint_address"],
        postgresql_where=sa.text(
            f"has_veto = false AND evidence >= {RANKING_HOT_MIN_EVIDENCE}"
        ),
    )
    op.create_index(
        "ix_token_scores_elite",
        "token_scores",
        [sa.text("score DESC")],
        postgresql_where=sa.text("is_elite"),
    )
    # The sweep's "which scores are stale?" scan.
    op.create_index("ix_token_scores_staleness", "token_scores", ["evaluated_at"])

    # --- Append-only history: carries the explanation payload ----------------
    op.create_table(
        "token_score_history",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        *_shared_columns(),
        sa.Column("grade", score_grade, nullable=False),
        sa.Column(
            "components",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("delta", SCORE, nullable=True),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_token_score_history"),
        sa.ForeignKeyConstraint(
            ["token_id"],
            ["discovered_tokens.id"],
            name="fk_token_score_history_token_id_discovered_tokens",
            ondelete="CASCADE",
        ),
        *_bounds(),
    )
    # "History for this token, newest first" - also the single-row lookup that
    # resolves a token's current component breakdown.
    op.create_index(
        "ix_score_history_mint_evaluated",
        "token_score_history",
        ["mint_address", sa.text("evaluated_at DESC")],
    )
    op.create_index(
        "ix_score_history_evaluated",
        "token_score_history",
        [sa.text("evaluated_at DESC")],
    )


def downgrade() -> None:
    op.drop_table("token_score_history")
    op.drop_table("token_scores")
    op.execute("DROP TYPE IF EXISTS score_grade")
