"""Graduation Lab: four new `grad_*` tables. Nothing existing is touched.

Purely additive: no ALTER, no DROP, no index on an existing table. A database
that runs this migration and never sets `LAB_GRADUATION_ENABLED` is
byte-identical in every table that existed before it.

Three columns differ from the brief's schema contract, each because the live
PumpPortal feed forced it:

* `name` and `symbol` on `grad_tokens` are NULLABLE — 17 of 121 consecutive
  `create` messages recorded on this socket carried neither.
* every `ts` is RECEIPT time — no message of any type carries a timestamp or a
  slot, so there is no other clock.
* `quote_currency` is ADDED — a USDC-denominated curve sends its reserve and
  its trade amount in USDC, and a column called `sol_amount` holding USDC is a
  silent unit error waiting for whoever queries this in six months.

Parented to 0065 on `karthik-hq`. Other branches carry their own 0066; the
revision ids differ, so the chains do not collide — but on `main` this lab's
migration needs renumbering and re-parenting, as the Rafiq lab's 0056 became
0063 there.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# 32 characters at most: alembic_version.version_num is varchar(32).
revision: str = "0066_graduation_lab"
down_revision: str = "0065_breakout_trader"
branch_labels = None
depends_on = None

_ADDRESS = sa.String(64)
_SIGNATURE = sa.String(96)
_SOL = sa.Numeric(30, 9)
_TOKENS = sa.Numeric(38, 9)
_PCT = sa.Numeric(6, 3)
_SHARE = sa.Numeric(9, 6)


def upgrade() -> None:
    op.create_table(
        "grad_tokens",
        sa.Column("mint", _ADDRESS, nullable=False),
        # Nullable: 17 of 121 consecutive live `create` messages carried
        # neither. See the module docstring.
        sa.Column("symbol", sa.String(32), nullable=True),
        sa.Column("name", sa.String(128), nullable=True),
        sa.Column("creator", _ADDRESS, nullable=True),
        sa.Column("launch_pool", sa.String(32), nullable=True),
        sa.Column("bonding_curve_key", _ADDRESS, nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tracked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("migrated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unsubscribed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unsubscribe_reason", sa.String(32), nullable=True),
        sa.Column("status", sa.String(16), nullable=False,
                  server_default=sa.text("'watching'")),
        sa.Column("max_progress_pct", _PCT, nullable=True),
        sa.Column("first_trade_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_trade_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trade_count", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("buy_count", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("sell_count", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("unique_traders", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("unique_buyers", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("volume_sol", _SOL, nullable=True),
        sa.Column("peak_market_cap_sol", _SOL, nullable=True),
        sa.Column("pruned_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("mint", name="pk_grad_tokens"),
    )
    op.create_index("ix_grad_tokens_first_seen_at", "grad_tokens",
                    ["first_seen_at"])
    op.create_index("ix_grad_tokens_status_first_seen", "grad_tokens",
                    ["status", "first_seen_at"])
    op.create_index("ix_grad_tokens_tracked_at", "grad_tokens", ["tracked_at"])
    op.create_index("ix_grad_tokens_migrated_at", "grad_tokens", ["migrated_at"])

    op.create_table(
        "grad_trades",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mint", _ADDRESS, nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("sol_amount", _SOL, nullable=False),
        sa.Column("token_amount", _TOKENS, nullable=False),
        sa.Column("trader", _ADDRESS, nullable=False),
        sa.Column("pool", sa.String(16), nullable=False),
        sa.Column("progress_pct", _PCT, nullable=True),
        sa.Column("v_token_reserves", _TOKENS, nullable=True),
        sa.Column("v_quote_reserves", _SOL, nullable=True),
        sa.Column("quote_currency", sa.String(8), nullable=True),
        sa.Column("market_cap_sol", _SOL, nullable=True),
        sa.Column("new_token_balance", _TOKENS, nullable=True),
        sa.Column("signature", _SIGNATURE, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_grad_trades"),
        # Dedupes the redelivery a reconnect can cause. NULL signatures do not
        # collide in Postgres, which is the behaviour wanted: an unsigned row
        # is not evidence of a duplicate.
        sa.UniqueConstraint("signature", "mint", name="uq_grad_trades_signature"),
    )
    op.create_index("ix_grad_trades_ts", "grad_trades", ["ts"])
    op.create_index("ix_grad_trades_mint_ts", "grad_trades", ["mint", "ts"])

    op.create_table(
        "grad_checkpoints",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("mint", _ADDRESS, nullable=False),
        sa.Column("level_pct", _PCT, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("progress_pct", _PCT, nullable=False),
        sa.Column("v_token_reserves", _TOKENS, nullable=True),
        sa.Column("v_quote_reserves", _SOL, nullable=True),
        sa.Column("quote_currency", sa.String(8), nullable=True),
        sa.Column("real_token_reserves", _TOKENS, nullable=True),
        sa.Column("market_cap_sol", _SOL, nullable=True),
        sa.Column("buy_count", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("sell_count", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("unique_buyers", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("unique_traders", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("top10_holder_share", _SHARE, nullable=True),
        sa.Column("holders_seen", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("id", name="pk_grad_checkpoints"),
        sa.UniqueConstraint("mint", "level_pct", name="uq_grad_checkpoints_mint"),
    )
    op.create_index("ix_grad_checkpoints_level_ts", "grad_checkpoints",
                    ["level_pct", "ts"])

    op.create_table(
        "grad_migrations",
        sa.Column("mint", _ADDRESS, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pool", sa.String(16), nullable=True),
        sa.Column("signature", _SIGNATURE, nullable=True),
        sa.Column("progress_pct_before", _PCT, nullable=True),
        # The whole message: PumpPortal publishes no example migration payload,
        # so the columns above are this lab's reading of an unverified shape
        # and this is the appeal against a misreading.
        sa.Column("raw", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("mint", name="pk_grad_migrations"),
    )
    op.create_index("ix_grad_migrations_ts", "grad_migrations", ["ts"])


def downgrade() -> None:
    op.drop_table("grad_migrations")
    op.drop_table("grad_checkpoints")
    op.drop_table("grad_trades")
    op.drop_table("grad_tokens")
