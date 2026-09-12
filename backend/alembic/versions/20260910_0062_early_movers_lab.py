"""Early Movers Lab: five new `em_*` tables. Nothing existing is touched.

Purely additive: no ALTER, no DROP, no index on an existing table. A database
that runs this migration and never enables `EARLY_MOVERS_ENABLED` is
byte-identical in every table that existed before it, and a test asserts that.

`em_launches` and `em_trades` are filled by the lab's recorder
(`app.labs.early_movers.recorder`); the feature engine only ever reads them.

Three columns differ from the brief's schema contract, each because the live
PumpPortal feed forced it:

* `name` and `symbol` are NULLABLE — 17 of 121 consecutive `create` messages
  recorded on 2026-09-10 carried neither.
* `slot` is NULLABLE — the feed sends no slot in any message.
* `initial_mc_sol` and `mc_sol_after` are ADDED — market caps arrive in SOL,
  and keeping the measured figure means a SOL/USD outage nulls the USD column
  recoverably instead of destroying the market cap for good.

Parented to 0061 on `karthik-hq`. Other branches carry their own 0062; the
revision ids differ, so the chains do not collide — but on `main` this lab's
migration would need renumbering and re-parenting, as the Rafiq lab's 0056
became 0063 there.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# 32 characters at most: alembic_version.version_num is varchar(32).
revision: str = "0062_early_movers_lab"
down_revision: str = "0061_crypto_trend_snapshots"
branch_labels = None
depends_on = None

_ADDRESS = sa.String(64)
_MC = sa.Numeric(24, 2)
_SOL = sa.Numeric(30, 9)


def upgrade() -> None:
    op.create_table(
        "em_launches",
        sa.Column("mint", _ADDRESS, nullable=False),
        # Nullable: 17 of 121 consecutive live `create` messages carried
        # neither. See the model's comment.
        sa.Column("name", sa.String(128), nullable=True),
        sa.Column("symbol", sa.String(32), nullable=True),
        sa.Column("creator", _ADDRESS, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("launch_platform", sa.String(32), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("initial_mc_usd", _MC, nullable=True),
        sa.Column("initial_mc_sol", _SOL, nullable=True),
        sa.PrimaryKeyConstraint("mint"),
    )
    op.create_index("ix_em_launches_created_at", "em_launches", ["created_at"])
    op.create_index("ix_em_launches_creator_created_at", "em_launches",
                    ["creator", "created_at"])

    op.create_table(
        "em_trades",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("mint", _ADDRESS, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("wallet", _ADDRESS, nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("sol_amount", sa.Numeric(30, 9), nullable=False),
        sa.Column("token_amount", sa.Numeric(38, 9), nullable=False),
        sa.Column("mc_usd_after", _MC, nullable=True),
        sa.Column("mc_sol_after", _SOL, nullable=True),
        # Nullable: the feed sends no slot. See the model's comment.
        sa.Column("slot", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["mint"], ["em_launches.mint"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_em_trades_mint_ts", "em_trades", ["mint", "ts"])

    op.create_table(
        "em_snapshots",
        sa.Column("mint", _ADDRESS, nullable=False),
        sa.Column("offset_sec", sa.Integer(), nullable=False),
        sa.Column("mc_usd", _MC, nullable=True),
        sa.Column("unique_buyers", sa.Integer(), nullable=False),
        sa.Column("unique_sellers", sa.Integer(), nullable=False),
        sa.Column("buy_sell_ratio", sa.Numeric(18, 6), nullable=True),
        sa.Column("holder_est", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["mint"], ["em_launches.mint"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("mint", "offset_sec"),
    )

    op.create_table(
        "em_features",
        sa.Column("mint", _ADDRESS, nullable=False),
        sa.Column("meta_cluster_id", _ADDRESS, nullable=True),
        sa.Column("is_meta_leader", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("copycat_count_10m", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("creator_prior_launches", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("creator_prior_grad_rate", sa.Numeric(6, 4), nullable=True),
        sa.Column("instant_mc_flag", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("bundled_flag", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("news_kw_hit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["mint"], ["em_launches.mint"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("mint"),
    )

    op.create_table(
        "em_creator_stats",
        sa.Column("creator", _ADDRESS, nullable=False),
        sa.Column("launches", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("graduations", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("avg_peak_mc", _MC, nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("creator"),
    )


def downgrade() -> None:
    op.drop_table("em_creator_stats")
    op.drop_table("em_features")
    op.drop_table("em_snapshots")
    op.drop_index("ix_em_trades_mint_ts", table_name="em_trades")
    op.drop_table("em_trades")
    op.drop_index("ix_em_launches_creator_created_at", table_name="em_launches")
    op.drop_index("ix_em_launches_created_at", table_name="em_launches")
    op.drop_table("em_launches")
