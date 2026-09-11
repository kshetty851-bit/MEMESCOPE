"""NSE Breakout Tracker phase 2: states, episodes and their events.

Purely additive: three new `bt_*` tables and one nullable column on
`bt_universe`. Nothing existing is altered or dropped, and a test asserts the
whole migration is `create_table` / `create_index` / `add_column` only.

`uq_bt_episodes_open` is PARTIAL — one open episode per symbol per source,
while closed episodes accumulate freely. That is the record, so it must not be
constrained.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0068_nse_bt_phase2"
down_revision: str = "0067_nse_breakout"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The replay's resumption marker. A symbol that produced no episodes has
    # still been replayed; without this it would be walked again for ever.
    op.add_column("bt_universe",
                  sa.Column("replayed_at", sa.DateTime(timezone=True),
                            nullable=True))
    op.create_table(
        "bt_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("bar_date", sa.Date(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("components", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("close", sa.Numeric(18, 4), nullable=False),
        sa.Column("resistance", sa.Numeric(18, 4), nullable=True),
        sa.Column("distance_pct", sa.Numeric(12, 4), nullable=True),
        sa.Column("range_pct", sa.Numeric(12, 4), nullable=True),
        sa.Column("tightness", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_52w_high", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("week52_high", sa.Numeric(18, 4), nullable=True),
        sa.Column("atr", sa.Numeric(18, 4), nullable=True),
        sa.Column("volume_mult", sa.Numeric(12, 4), nullable=True),
        sa.Column("clusters", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("days_in_state", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("bars", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("symbol", name="uq_bt_states_symbol"),
    )
    op.create_index("ix_bt_states_state_score", "bt_states", ["state", "score"])
    op.create_table(
        "bt_episodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("source", sa.String(8), nullable=False),
        sa.Column("opened", sa.Date(), nullable=False),
        sa.Column("first_near_date", sa.Date(), nullable=True),
        sa.Column("ref_price", sa.Numeric(18, 4), nullable=True),
        sa.Column("resistance", sa.Numeric(18, 4), nullable=True),
        sa.Column("score_at_open", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_score", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("breakout_date", sa.Date(), nullable=True),
        sa.Column("breakout_price", sa.Numeric(18, 4), nullable=True),
        sa.Column("breakout_volume_mult", sa.Numeric(12, 4), nullable=True),
        sa.Column("days_to_breakout", sa.Integer(), nullable=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("bars_open", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("bars_since_breakout", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("weak_bars", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("closed", sa.Date(), nullable=True),
        sa.Column("close_reason", sa.String(24), nullable=True),
        sa.Column("ret_ref_5", sa.Numeric(12, 4), nullable=True),
        sa.Column("ret_ref_10", sa.Numeric(12, 4), nullable=True),
        sa.Column("ret_ref_20", sa.Numeric(12, 4), nullable=True),
        sa.Column("ret_ref_40", sa.Numeric(12, 4), nullable=True),
        sa.Column("mfe_20", sa.Numeric(12, 4), nullable=True),
        sa.Column("mae_20", sa.Numeric(12, 4), nullable=True),
        sa.Column("ret_bo_5", sa.Numeric(12, 4), nullable=True),
        sa.Column("ret_bo_10", sa.Numeric(12, 4), nullable=True),
        sa.Column("ret_bo_20", sa.Numeric(12, 4), nullable=True),
        sa.Column("ret_bo_40", sa.Numeric(12, 4), nullable=True),
        sa.Column("mfe_bo_20", sa.Numeric(12, 4), nullable=True),
        sa.Column("mae_bo_20", sa.Numeric(12, 4), nullable=True),
        sa.Column("held_20d_pct", sa.Numeric(12, 4), nullable=True),
        sa.Column("trail10_pct", sa.Numeric(12, 4), nullable=True),
        sa.Column("trail10_bars", sa.Integer(), nullable=True),
        sa.Column("trail10_stopped", sa.Boolean(), nullable=True),
        sa.Column("rel_nifty_20", sa.Numeric(12, 4), nullable=True),
        sa.Column("rel_nifty_bo_20", sa.Numeric(12, 4), nullable=True),
        sa.Column("outcomes_filled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_bt_episodes_breakout", "bt_episodes", ["source", "breakout_date"])
    op.create_index("uq_bt_episodes_open", "bt_episodes", ["symbol", "source"], unique=True, postgresql_where=sa.text("closed IS NULL"))
    op.create_index("ix_bt_episodes_source_opened", "bt_episodes", ["source", "opened"])
    op.create_table(
        "bt_episode_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("episode_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("close", sa.Numeric(18, 4), nullable=True),
        sa.Column("resistance", sa.Numeric(18, 4), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.create_index("ix_bt_episode_events_episode", "bt_episode_events", ["episode_id", "date"])


def downgrade() -> None:
    op.drop_index("ix_bt_episode_events_episode", table_name="bt_episode_events")
    op.drop_table("bt_episode_events")
    op.drop_index("ix_bt_episodes_source_opened", table_name="bt_episodes")
    op.drop_index("uq_bt_episodes_open", table_name="bt_episodes")
    op.drop_index("ix_bt_episodes_breakout", table_name="bt_episodes")
    op.drop_table("bt_episodes")
    op.drop_index("ix_bt_states_state_score", table_name="bt_states")
    op.drop_table("bt_states")
    op.drop_column("bt_universe", "replayed_at")
