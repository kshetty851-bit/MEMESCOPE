"""Meme Lifecycle Lab: `mll_replay_checkpoints`, the incremental replay's state.

One current row per scope (mode | arm | experiment | hindsight), unique on
`scope_key`; history is not kept. A row is a cache with a proof attached —
`app/lifecycle_lab/checkpoint.py` decides whether it may be resumed — so
dropping the table (or any row) costs one full replay and changes no result.

Both foreign keys cascade: a checkpoint is meaningless without the experiment
it was computed under or the run whose rows it was written alongside.

Revision ID: 0113_mll_replay_checkpoints
Revises: 0112_meme_lifecycle_lab
Create Date: 2026-10-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0113_mll_replay_checkpoints"
down_revision: str | None = "0112_meme_lifecycle_lab"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TS = sa.DateTime(timezone=True)
_TABLE = "mll_replay_checkpoints"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("scope_key", sa.String(length=256), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("arm", sa.String(length=64), nullable=False),
        sa.Column("experiment_id", sa.UUID(), nullable=False),
        sa.Column("backtest_run_id", sa.UUID(), nullable=False),
        sa.Column("replay_version", sa.String(length=48), nullable=False),
        sa.Column("engine_hash", sa.String(length=64), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("spec_hash", sa.String(length=64), nullable=False),
        sa.Column("window_start", _TS, nullable=False),
        sa.Column("processed_until", _TS, nullable=False),
        sa.Column("input_watermark", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("state_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", _TS, server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", _TS, server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["mll_experiments.id"],
            name="fk_mll_replay_checkpoints_experiment_id_mll_experiments",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["backtest_run_id"],
            ["mll_backtest_runs.id"],
            name="fk_mll_replay_checkpoints_backtest_run_id_mll_backtest_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_mll_replay_checkpoints"),
        sa.UniqueConstraint("scope_key", name="uq_mll_replay_checkpoints_scope_key"),
    )
    # TimestampMixin declares `index=True`; without this `alembic check` fails.
    op.create_index(f"ix_{_TABLE}_created_at", _TABLE, ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(f"ix_{_TABLE}_created_at", table_name=_TABLE)
    op.drop_table(_TABLE)
