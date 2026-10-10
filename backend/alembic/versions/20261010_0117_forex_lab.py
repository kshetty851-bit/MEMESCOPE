"""Forex Strategy Lab: candles, import batches, fetch cache, versions, runs.

Research and paper only. `forex_candles` is insert-only (`ON CONFLICT DO NOTHING`
in the repository); an older `fx_candles` table was dropped in 0103, so every
table here carries the `forex_` prefix.

`created_at` is indexed on every table because `TimestampMixin` declares it -
omit it and `alembic check` reports drift.

Revision ID: 0117_forex_lab
Revises: 0116_boost_picks
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0117_forex_lab"
down_revision: str = "0116_boost_picks"
branch_labels = None
depends_on = None

_PRICE = sa.Numeric(12, 6)


def _stamps() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "forex_import_batches",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("filename", sa.String(256), nullable=False),
        sa.Column("rows_total", sa.Integer(), nullable=False),
        sa.Column("rows_accepted", sa.Integer(), nullable=False),
        sa.Column("rows_inserted", sa.Integer(), nullable=False),
        sa.Column("rows_existing", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("errors", postgresql.JSONB(), nullable=False),
        sa.Column("detected_format", sa.String(16), nullable=False),
        sa.Column("start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quality", postgresql.JSONB(), nullable=True),
        sa.Column("notes", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        *_stamps(),
        sa.PrimaryKeyConstraint("id", name="pk_forex_import_batches"),
    )
    op.create_index(
        "ix_forex_import_batches_created_at", "forex_import_batches", ["created_at"]
    )

    op.create_table(
        "forex_candles",
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", _PRICE, nullable=False),
        sa.Column("high", _PRICE, nullable=False),
        sa.Column("low", _PRICE, nullable=False),
        sa.Column("close", _PRICE, nullable=False),
        sa.Column("volume", sa.Numeric(20, 4), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("import_batch_id", sa.Integer(), nullable=True),
        *_stamps(),
        sa.PrimaryKeyConstraint("symbol", "timeframe", "open_time", name="pk_forex_candles"),
        sa.ForeignKeyConstraint(
            ["import_batch_id"],
            ["forex_import_batches.id"],
            name="fk_forex_candles_import_batch_id_forex_import_batches",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_forex_candles_created_at", "forex_candles", ["created_at"])

    op.create_table(
        "forex_fetch_days",
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("empty", sa.Boolean(), nullable=False),
        sa.Column("candles", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(256), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        *_stamps(),
        sa.PrimaryKeyConstraint("provider", "symbol", "day", name="pk_forex_fetch_days"),
    )
    op.create_index("ix_forex_fetch_days_created_at", "forex_fetch_days", ["created_at"])

    op.create_table(
        "forex_strategy_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("strategy", sa.String(32), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        *_stamps(),
        sa.PrimaryKeyConstraint("id", name="pk_forex_strategy_versions"),
        sa.UniqueConstraint("name", "version", name="uq_forex_strategy_versions_name_version"),
    )
    op.create_index(
        "ix_forex_strategy_versions_created_at", "forex_strategy_versions", ["created_at"]
    )

    op.create_table(
        "forex_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("message", sa.String(256), nullable=True),
        sa.Column("name", sa.String(120), nullable=True),
        sa.Column("strategy_version_id", sa.Integer(), nullable=True),
        sa.Column("config", postgresql.JSONB(), nullable=True),
        sa.Column("request", postgresql.JSONB(), nullable=False),
        sa.Column("data_fingerprint", sa.String(64), nullable=True),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("app_version", sa.String(32), nullable=False),
        sa.Column("summary", postgresql.JSONB(), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
        sa.PrimaryKeyConstraint("id", name="pk_forex_runs"),
        sa.ForeignKeyConstraint(
            ["strategy_version_id"],
            ["forex_strategy_versions.id"],
            name="fk_forex_runs_strategy_version_id_forex_strategy_versions",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_forex_runs_created_at", "forex_runs", ["created_at"])
    # Listing is `WHERE kind = ? ORDER BY created_at DESC, id DESC LIMIT n`.
    op.create_index(
        "ix_forex_runs_kind_created",
        "forex_runs",
        ["kind", sa.text("created_at DESC"), sa.text("id DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_forex_runs_kind_created", table_name="forex_runs")
    op.drop_index("ix_forex_runs_created_at", table_name="forex_runs")
    op.drop_table("forex_runs")
    op.drop_index(
        "ix_forex_strategy_versions_created_at", table_name="forex_strategy_versions"
    )
    op.drop_table("forex_strategy_versions")
    op.drop_index("ix_forex_fetch_days_created_at", table_name="forex_fetch_days")
    op.drop_table("forex_fetch_days")
    op.drop_index("ix_forex_candles_created_at", table_name="forex_candles")
    op.drop_table("forex_candles")
    op.drop_index("ix_forex_import_batches_created_at", table_name="forex_import_batches")
    op.drop_table("forex_import_batches")
