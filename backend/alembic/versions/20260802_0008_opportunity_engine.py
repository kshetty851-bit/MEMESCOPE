"""Opportunity Engine foundation.

Two new tables and eight new `event_kind` values. Purely additive: no existing
table, column, index or constraint is touched, so the scanner, enrichment,
scoring and the Radar are unaffected and this applies while they run.

**Why two tables rather than the one ARCHITECTURE_DECISIONS.md AD-05 proposed.**
The header cannot live on `radar_tokens` without changing Radar behaviour, which
Sprint 4 forbids:

  * `uq_radar_tokens_mint_address` is unique on `mint_address` alone and the
    Radar's detector inserts with `ON CONFLICT (mint_address) DO NOTHING`.
    Widening it to `(mint_address, generation)` breaks that insert.
  * Eight `NOT NULL` columns on `radar_tokens` belong to the Radar's scoring
    model. An opportunity raised by a signal provider has none of them, and
    supplying invented values would put fabricated scores on the Radar board.

The header therefore gets its own table. It duplicates no token data: identity
stays in `discovered_tokens` behind a foreign key, with `mint_address`
denormalised for join-free per-token reads — the same pattern every other table
here uses.

**The `event_kind` additions change no existing semantics.** Every value that
already existed keeps the meaning it has always had, and no existing detector
emits any of the new ones. `ADD VALUE IF NOT EXISTS` is safe inside a
transaction on PostgreSQL 12+ provided the value is not *used* in the same
transaction, which it is not.

Revision ID: 0008_opportunity
Revises: 0007_maintenance
Create Date: 2026-08-02 19:05:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_opportunity"
down_revision: str | None = "0007_maintenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Statuses that occupy a token's live slot. Kept in step with
#: `app.opportunities.models.LIVE_STATUSES`; a unit test asserts they match, so
#: adding a live status cannot leave this index behind.
_LIVE_STATUSES = ("active", "expiring", "new", "pending_confirmation")
_LIVE_STATUS_SQL = ", ".join(f"'{status}'" for status in _LIVE_STATUSES)

_NEW_EVENT_KINDS = (
    "opportunity_opened",
    "opportunity_confirmed",
    "opportunity_expiring",
    "opportunity_closed",
    "opportunity_archived",
    "signal_added",
    "signal_confirmed",
    "signal_expired",
)


def upgrade() -> None:
    for kind in _NEW_EVENT_KINDS:
        op.execute(f"ALTER TYPE event_kind ADD VALUE IF NOT EXISTS '{kind}'")

    op.create_table(
        "opportunities",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("token_id", sa.UUID(), nullable=False),
        sa.Column("mint_address", sa.String(length=44), nullable=False),
        sa.Column("generation", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column(
            "priority", sa.Numeric(precision=5, scale=2), server_default="0", nullable=False
        ),
        sa.Column("priority_band", sa.String(length=16), nullable=False),
        sa.Column(
            "confidence", sa.Numeric(precision=5, scale=2), server_default="0", nullable=False
        ),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_confirmed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expiring_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("generation >= 1", name="ck_opportunities_generation_positive"),
        sa.ForeignKeyConstraint(
            ["token_id"],
            ["discovered_tokens.id"],
            name="fk_opportunities_token_id_discovered_tokens",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_opportunities"),
        sa.UniqueConstraint("mint_address", "generation", name="uq_opportunities_mint_gen"),
    )
    # The AD-09 guarantee: at most one live opportunity per token. Two workers
    # racing on the same mint cannot both win — the loser's insert conflicts and
    # it reads the winner's row.
    op.create_index(
        "uq_opportunities_live_mint",
        "opportunities",
        ["mint_address"],
        unique=True,
        postgresql_where=sa.text(f"status IN ({_LIVE_STATUS_SQL})"),
    )
    op.create_index(
        "ix_opportunities_live_priority",
        "opportunities",
        [sa.text("priority DESC")],
        unique=False,
        postgresql_where=sa.text(f"status IN ({_LIVE_STATUS_SQL})"),
    )
    op.create_index(
        "ix_opportunities_status_confirmed",
        "opportunities",
        ["status", "last_confirmed_at"],
        unique=False,
    )
    op.create_index(
        "ix_opportunities_detected",
        "opportunities",
        [sa.text("detected_at DESC")],
        unique=False,
    )
    # From `TimestampMixin`, which indexes `created_at` on every table it is
    # mixed into. Declared here so `alembic check` stays clean; whether that
    # mixin should index at all is a separate, repo-wide question raised in
    # MEMESCOPE_AUDIT.md.
    op.create_index(
        "ix_opportunities_created_at", "opportunities", ["created_at"], unique=False
    )

    op.create_table(
        "opportunity_signals",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("opportunity_id", sa.UUID(), nullable=False),
        sa.Column("mint_address", sa.String(length=44), nullable=False),
        sa.Column("signal_type", sa.String(length=48), nullable=False),
        sa.Column("provider_id", sa.String(length=48), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("strength", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column(
            "confidence", sa.Numeric(precision=5, scale=2), server_default="0", nullable=False
        ),
        sa.Column("confirmations", sa.Integer(), server_default="1", nullable=False),
        sa.Column("observations", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_confirmed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "reason_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
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
        sa.CheckConstraint("confirmations >= 1", name="ck_opportunity_signals_confirmations"),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunities.id"],
            name="fk_opportunity_signals_opportunity_id_opportunities",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_opportunity_signals"),
        # No duplicate active signal. A re-detection collides here and is
        # treated as a confirmation rather than inserting a second row.
        sa.UniqueConstraint(
            "opportunity_id",
            "signal_type",
            "provider_id",
            name="uq_opportunity_signals_dedupe",
        ),
    )
    op.create_index(
        "ix_opportunity_signals_expiry",
        "opportunity_signals",
        ["status", "expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_opportunity_signals_opportunity",
        "opportunity_signals",
        ["opportunity_id"],
        unique=False,
    )
    op.create_index(
        "ix_opportunity_signals_mint", "opportunity_signals", ["mint_address"], unique=False
    )
    op.create_index(
        "ix_opportunity_signals_created_at",
        "opportunity_signals",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_opportunity_signals_created_at", table_name="opportunity_signals")
    op.drop_index("ix_opportunity_signals_mint", table_name="opportunity_signals")
    op.drop_index("ix_opportunity_signals_opportunity", table_name="opportunity_signals")
    op.drop_index("ix_opportunity_signals_expiry", table_name="opportunity_signals")
    op.drop_table("opportunity_signals")

    op.drop_index("ix_opportunities_created_at", table_name="opportunities")
    op.drop_index("ix_opportunities_detected", table_name="opportunities")
    op.drop_index("ix_opportunities_status_confirmed", table_name="opportunities")
    op.drop_index("ix_opportunities_live_priority", table_name="opportunities")
    op.drop_index("uq_opportunities_live_mint", table_name="opportunities")
    op.drop_table("opportunities")

    # The enum values are deliberately left in place. PostgreSQL cannot remove a
    # value from an enum type without rewriting every column that uses it, and
    # `intelligence_events` is append-only — a downgrade that rewrote it would
    # do more damage than the values it removed. They are inert without the
    # tables above.
