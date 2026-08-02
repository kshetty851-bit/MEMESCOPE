"""Ranking index correction, dead index removal, and autovacuum tuning.

Three operational repairs from MEMESCOPE_AUDIT.md §6. No table is rewritten and
no column changes, so this applies while the pipeline runs.

**1. `/scores/top` had no usable index.** `ix_token_scores_ranking` leads with
`model_version`, but the endpoint sends an equality on that column only when a
caller passes `?model_version=`, which the frontend never does. Postgres
therefore seq-scanned `token_scores`, hash-joined `discovered_tokens` and
top-N sorted 20,225 rows to return 20. `ix_token_scores_ranking_default` leads
with the sort key instead.

**2. Two indexes were provably dead.** Each is justified in its own comment
below. `ix_token_scores_ranking` is deliberately **kept** despite zero recorded
scans: it serves `?model_version=`, a supported filter, and the drain path a
model promotion runs. Zero scans there means "nobody has passed the parameter",
not "the index cannot be used" — a distinction the two dropped indexes fail.

**3. Autovacuum has never recorded an analyze on the two largest tables.**
Measured rather than assumed, the damage is smaller than the audit claimed:
`pg_class.reltuples` — the figure the planner actually reads — was within 9% of
the truth, and column statistics were present and sane. The audit's "wrong by
97x" came from `pg_stat_user_tables.n_live_tup`, a separate activity counter
that is discarded on an unclean shutdown and that no planner consults. Running
ANALYZE changed no query plan and no endpoint latency.

The tuning below is therefore preventative, not a fix: at the default 10%
scale factor a table with 1.7 M rows needs 172,000 new rows before the planner
learns anything, and both of these grow continuously.

This migration does **not** run VACUUM or ANALYZE. VACUUM cannot run inside a
transaction block, and a migration that silently rewrites 2.5 GB is not
something anyone should discover mid-deploy. It sets the storage parameters
that make autovacuum keep up from here; the one-off catch-up is an explicit
operator action — `make db-analyze`, or `python -m app.db.maintenance`. See
docs/DEPLOYMENT.md.

Revision ID: 0007_maintenance
Revises: 7969db20724a
Create Date: 2026-08-02 18:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_maintenance"
down_revision: str | None = "7969db20724a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: Analyze once per ~1% of the table rather than the default 10%. On a table
#: with 1.7 M rows the default means 172,000 new rows before the planner learns
#: anything, and these two tables are append-only and grow continuously — the
#: estimate is stale for most of the interval by construction. The fixed
#: threshold keeps small tables from analyzing constantly.
_AUTOVACUUM_TUNING = {
    "token_market_snapshots": {
        "autovacuum_analyze_scale_factor": "0.01",
        "autovacuum_analyze_threshold": "5000",
        # Append-only: rows are never updated or deleted, so the only vacuum
        # work that matters is freezing and the visibility map — which is what
        # makes index-only scans possible on the trending queries.
        "autovacuum_vacuum_insert_scale_factor": "0.05",
    },
    "token_score_history": {
        "autovacuum_analyze_scale_factor": "0.01",
        "autovacuum_analyze_threshold": "5000",
        "autovacuum_vacuum_insert_scale_factor": "0.05",
    },
    "discovered_tokens": {
        "autovacuum_analyze_scale_factor": "0.02",
        "autovacuum_analyze_threshold": "1000",
    },
}

#: Restores the server defaults, so a downgrade leaves no per-table override
#: behind pretending to be deliberate.
_TUNED_PARAMETERS = (
    "autovacuum_analyze_scale_factor",
    "autovacuum_analyze_threshold",
    "autovacuum_vacuum_insert_scale_factor",
)


def upgrade() -> None:
    # --- 1. The ranking index `/scores/top` can actually use ----------------
    # `IS false`, not `= false`: SQLAlchemy compiles `has_veto.is_(False)` to
    # `has_veto IS false`, and Postgres will not prove that implies `= false`.
    # An index whose predicate the planner cannot match is never used — which
    # is precisely the defect being repaired here, so getting the operator
    # wrong would reproduce it under a new name.
    op.create_index(
        "ix_token_scores_ranking_default",
        "token_scores",
        [sa.text("score DESC"), "mint_address"],
        unique=False,
        postgresql_where=sa.text("has_veto IS false"),
    )

    # --- 2. Provably dead indexes -------------------------------------------
    # Required `evidence >= 25`, which no query the application issues implies:
    # `min_confidence` is optional on `/scores/top` and unset by default, so
    # Postgres could never prove the partial predicate held. Unusable by
    # construction, not merely unused. Superseded by the index created above,
    # which serves every query this one could have.
    op.drop_index("ix_token_scores_ranking_hot", table_name="token_scores")

    # A DESC btree on the same single column as the existing ascending
    # `ix_discovered_tokens_discovered_at`. Postgres scans a btree backward at
    # the same cost as forward, so this index can serve no query the ascending
    # one cannot. Pure duplicate write cost on the discovery insert path.
    op.drop_index("ix_discovered_tokens_discovered_at_desc", table_name="discovered_tokens")

    # `signature` is stored for provenance and is never filtered, joined or
    # sorted on anywhere in the application — verified by grep across
    # `app/`, not by the scan counter alone. Ingestion deduplicates on
    # `mint_address`, which has its own unique index. 3.7 MB of write
    # amplification on the hottest insert path in the system, serving nothing.
    op.drop_index("ix_discovered_tokens_signature", table_name="discovered_tokens")

    # --- 3. Keep the planner's estimates honest -----------------------------
    for table, parameters in _AUTOVACUUM_TUNING.items():
        settings = ", ".join(f"{key} = {value}" for key, value in parameters.items())
        op.execute(f"ALTER TABLE {table} SET ({settings})")


def downgrade() -> None:
    for table, parameters in _AUTOVACUUM_TUNING.items():
        resettable = ", ".join(key for key in _TUNED_PARAMETERS if key in parameters)
        op.execute(f"ALTER TABLE {table} RESET ({resettable})")

    op.create_index(
        "ix_discovered_tokens_signature", "discovered_tokens", ["signature"], unique=False
    )
    op.create_index(
        "ix_discovered_tokens_discovered_at_desc",
        "discovered_tokens",
        [sa.text("discovered_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_token_scores_ranking_hot",
        "token_scores",
        ["model_version", sa.text("score DESC"), "mint_address"],
        unique=False,
        postgresql_where=sa.text("has_veto = false AND evidence >= 25"),
    )
    op.drop_index("ix_token_scores_ranking_default", table_name="token_scores")
