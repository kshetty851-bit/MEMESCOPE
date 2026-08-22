"""HQ operations: incidents and the autonomous-action audit trail.

Two new tables, no existing table touched. That is not incidental — the HQ
brief forbids reshaping a trading table for HQ's convenience, and the reason
holds on its own: an observability feature that shares storage with the paper
wallet is an observability feature that can corrupt the paper wallet. There is
no foreign key from here into anything that trades, and nothing that trades
reads from here.

`hq_actions` is append-only by convention rather than by constraint — the
service writes a row before an action runs and completes it after, so an
action that kills the process still leaves evidence it was attempted. A
trigger enforcing immutability was considered and skipped: it would also block
that completion write, and the value is in having the row at all.

Chained on 0042 rather than 0041 to keep a single head. 0042 was written by a
concurrent session and, at the time of writing, is applied to the development
database but not yet committed — branching around it would recreate the exact
divergence that crash-looped this backend once already.

Revision ID: 0043_hq_ops
Revises: 0042_kill_switch_clear
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0043_hq_ops"
down_revision = "0042_kill_switch_clear"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hq_incidents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("code", sa.String(24), nullable=False, unique=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("component", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("autonomy", sa.String(8), nullable=False),
        sa.Column("agent", sa.String(32), nullable=True),
        sa.Column("signature", sa.String(128), nullable=False),
        sa.Column(
            "symptoms",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("owner_rationale", sa.Text(), nullable=True),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # The detector asks "is this condition already open" on every single tick.
    # Without this index that question is a sequential scan of every incident
    # the system has ever had, forever.
    op.create_index(
        "ix_hq_incidents_signature_status", "hq_incidents", ["signature", "status"]
    )
    op.create_index(
        "ix_hq_incidents_status_detected", "hq_incidents", ["status", "detected_at"]
    )
    op.create_index("ix_hq_incidents_kind_detected", "hq_incidents", ["kind", "detected_at"])

    op.create_table(
        "hq_actions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "incident_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hq_incidents.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("agent", sa.String(32), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("autonomy", sa.String(8), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column(
            "preconditions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "verification",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )
    op.create_index("ix_hq_actions_at", "hq_actions", ["at"])
    op.create_index("ix_hq_actions_incident", "hq_actions", ["incident_id", "at"])


def downgrade() -> None:
    op.drop_index("ix_hq_actions_incident", table_name="hq_actions")
    op.drop_index("ix_hq_actions_at", table_name="hq_actions")
    op.drop_table("hq_actions")
    op.drop_index("ix_hq_incidents_kind_detected", table_name="hq_incidents")
    op.drop_index("ix_hq_incidents_status_detected", table_name="hq_incidents")
    op.drop_index("ix_hq_incidents_signature_status", table_name="hq_incidents")
    op.drop_table("hq_incidents")
