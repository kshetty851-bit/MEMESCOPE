"""V4 Phase 2: research-data foundation. Additive only.

Seven new tables and three annotation columns on `token_market_snapshots`.
No existing row is modified, no table dropped, no index removed. The snapshot
column additions use server defaults, which PostgreSQL applies as metadata —
no rewrite of the 5.7M-row table happens during this migration.

Chains off `0044_karthik_wallet` — PRODUCTION's head — keeping the graph
single-headed. The divergent `0044_paper_wallet_v2` chain exists only as
untracked files in a development worktree and is deliberately not a parent.

Revision ID: 0045_v4_phase2
Revises: 0044_karthik_wallet
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0045_v4_phase2"
down_revision = "0044_karthik_wallet"
branch_labels = None
depends_on = None

PRICE = sa.Numeric(38, 18)
MONEY = sa.Numeric(24, 4)
PCT = sa.Numeric(8, 4)
SHARE = sa.Numeric(8, 6)


def _uuid_pk() -> sa.Column:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )


def _stamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    # --- ingest firewall annotations -------------------------------------
    op.add_column(
        "token_market_snapshots",
        sa.Column("suspect", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "token_market_snapshots",
        sa.Column("suspect_reason", sa.String(32), nullable=True),
    )
    op.add_column(
        "token_market_snapshots",
        sa.Column("baseline_price_usd", PRICE, nullable=True),
    )

    # --- nursery lifecycle -------------------------------------------------
    op.create_table(
        "nursery_admissions",
        _uuid_pk(),
        sa.Column(
            "token_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("discovered_tokens.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mint_address", sa.String(44), nullable=False),
        sa.Column(
            "entered_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), server_default="observing", nullable=False),
        sa.Column("window_minutes", sa.Integer(), nullable=False),
        sa.Column("entry_score", sa.Numeric(8, 2), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason", sa.String(64), nullable=True),
        sa.Column("admitted_at", sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_id", name="uq_nursery_admissions_token_id"),
        sa.CheckConstraint(
            "status IN ('observing','qualified','rejected','expired')",
            name="ck_nursery_admissions_status",
        ),
    )
    op.create_index("ix_nursery_admissions_mint_address", "nursery_admissions", ["mint_address"])
    op.create_index("ix_nursery_admissions_status_entered", "nursery_admissions", ["status", "entered_at"])
    op.create_index("ix_nursery_admissions_created_at", "nursery_admissions", ["created_at"])

    # --- wallet-flow snapshots ----------------------------------------------
    flow_cols: list[sa.Column] = []
    for w in ("w5m", "w1h"):
        flow_cols += [
            sa.Column(f"{w}_unique_buyers", sa.Integer(), nullable=True),
            sa.Column(f"{w}_unique_sellers", sa.Integer(), nullable=True),
            sa.Column(f"{w}_unique_wallets", sa.Integer(), nullable=True),
            sa.Column(f"{w}_buy_count", sa.Integer(), nullable=True),
            sa.Column(f"{w}_sell_count", sa.Integer(), nullable=True),
            sa.Column(f"{w}_buy_volume", sa.BigInteger(), nullable=True),
            sa.Column(f"{w}_sell_volume", sa.BigInteger(), nullable=True),
            sa.Column(f"{w}_tx_per_wallet", sa.Numeric(12, 4), nullable=True),
            sa.Column(f"{w}_repeat_wallet_ratio", SHARE, nullable=True),
            sa.Column(f"{w}_top5_tx_share", SHARE, nullable=True),
            sa.Column(f"{w}_top10_tx_share", SHARE, nullable=True),
            sa.Column(f"{w}_top5_volume_share", SHARE, nullable=True),
            sa.Column(f"{w}_top10_volume_share", SHARE, nullable=True),
            sa.Column(f"{w}_largest_buyer_share", SHARE, nullable=True),
            sa.Column(f"{w}_largest_seller_share", SHARE, nullable=True),
            sa.Column(f"{w}_quality", sa.String(8), nullable=True),
        ]
    op.create_table(
        "wallet_flow_snapshots",
        _uuid_pk(),
        sa.Column("key", sa.String(44), nullable=False),
        sa.Column("key_kind", sa.String(4), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        *flow_cols,
        *_stamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("key_kind IN ('mint','pool')", name="ck_wallet_flow_key_kind"),
    )
    op.create_index("ix_wallet_flow_snapshots_key_captured", "wallet_flow_snapshots", ["key", "captured_at"])
    op.create_index("ix_wallet_flow_snapshots_created_at", "wallet_flow_snapshots", ["created_at"])

    # --- holder snapshots ----------------------------------------------------
    op.create_table(
        "holder_snapshots",
        _uuid_pk(),
        sa.Column(
            "token_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("discovered_tokens.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("mint_address", sa.String(44), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider", sa.String(24), nullable=False),
        sa.Column("context", sa.String(16), nullable=False),
        sa.Column("supply_raw", sa.Numeric(40, 0), nullable=True),
        sa.Column("decimals", sa.SmallInteger(), nullable=True),
        sa.Column("top1_pct", PCT, nullable=True),
        sa.Column("top5_pct", PCT, nullable=True),
        sa.Column("top10_pct", PCT, nullable=True),
        sa.Column("creator_pct", PCT, nullable=True),
        sa.Column("largest_nonpool_pct", PCT, nullable=True),
        sa.Column("accounts", postgresql.JSONB(), nullable=True),
        sa.Column("excluded", postgresql.JSONB(), nullable=True),
        sa.Column("failure_reason", sa.String(64), nullable=True),
        *_stamps(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_holder_snapshots_mint_captured", "holder_snapshots", ["mint_address", "captured_at"])
    op.create_index("ix_holder_snapshots_created_at", "holder_snapshots", ["created_at"])

    # --- research quotes -------------------------------------------------------
    op.create_table(
        "research_quotes",
        _uuid_pk(),
        sa.Column("mint_address", sa.String(44), nullable=False),
        sa.Column(
            "token_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("discovered_tokens.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("size_usd", MONEY, nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("in_amount_raw", sa.Numeric(30, 0), nullable=True),
        sa.Column("out_amount_raw", sa.Numeric(30, 0), nullable=True),
        sa.Column("price_impact_pct", sa.Numeric(12, 6), nullable=True),
        sa.Column("route", sa.String(255), nullable=True),
        sa.Column("failure_reason", sa.String(64), nullable=True),
        sa.Column("price_usd_at", PRICE, nullable=True),
        sa.Column("liquidity_usd_at", MONEY, nullable=True),
        sa.Column("context", sa.String(24), nullable=False),
        *_stamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("side IN ('buy','sell')", name="ck_research_quotes_side"),
    )
    op.create_index("ix_research_quotes_mint_requested", "research_quotes", ["mint_address", "requested_at"])
    op.create_index("ix_research_quotes_created_at", "research_quotes", ["created_at"])

    # --- regime telemetry -------------------------------------------------------
    op.create_table(
        "regime_snapshots",
        _uuid_pk(),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        *_stamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("kind IN ('population','market')", name="ck_regime_snapshots_kind"),
    )
    op.create_index("ix_regime_snapshots_captured_at", "regime_snapshots", ["captured_at"])
    op.create_index("ix_regime_snapshots_created_at", "regime_snapshots", ["created_at"])

    # --- executable outcomes beside the immutable record ------------------------
    op.create_table(
        "radar_executable_outcomes",
        sa.Column(
            "radar_token_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("radar_tokens.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("method_version", sa.String(16), nullable=False),
        sa.Column("executable_peak_multiple", sa.Numeric(20, 6), nullable=True),
        sa.Column("reached_125_24h", sa.Boolean(), nullable=True),
        sa.Column("reached_2x_24h", sa.Boolean(), nullable=True),
        sa.Column("reached_2x_72h", sa.Boolean(), nullable=True),
        sa.Column("final_value_frac_24h", sa.Numeric(20, 6), nullable=True),
        sa.Column("decided_24h", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("snapshots_used", sa.Integer(), nullable=True),
        sa.Column("suspects_excluded", sa.Integer(), nullable=True),
        *_stamps(),
        sa.PrimaryKeyConstraint("radar_token_id"),
    )
    op.create_index("ix_radar_executable_outcomes_created_at", "radar_executable_outcomes", ["created_at"])

    # --- daily Jupiter verified universe -----------------------------------------
    op.create_table(
        "jupiter_universe_snapshots",
        _uuid_pk(),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("mint_address", sa.String(44), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=True),
        sa.Column("provider_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("liquidity_usd", MONEY, nullable=True),
        sa.Column("market_cap", MONEY, nullable=True),
        sa.Column("holder_count", sa.Integer(), nullable=True),
        sa.Column("organic_score", sa.Numeric(8, 2), nullable=True),
        *_stamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_date", "mint_address", name="uq_universe_date_mint"),
    )
    op.create_index("ix_jupiter_universe_snapshot_date", "jupiter_universe_snapshots", ["snapshot_date"])
    op.create_index("ix_jupiter_universe_snapshots_created_at", "jupiter_universe_snapshots", ["created_at"])


def downgrade() -> None:
    for table in (
        "jupiter_universe_snapshots",
        "radar_executable_outcomes",
        "regime_snapshots",
        "research_quotes",
        "holder_snapshots",
        "wallet_flow_snapshots",
        "nursery_admissions",
    ):
        op.drop_table(table)
    op.drop_column("token_market_snapshots", "baseline_price_usd")
    op.drop_column("token_market_snapshots", "suspect_reason")
    op.drop_column("token_market_snapshots", "suspect")
