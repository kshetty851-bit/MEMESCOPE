"""Paper wallet: two tables, and deliberately only two.

`paper_wallets` holds one row per strategy; `paper_positions` holds one row per
simulated trade. Everything else the wallet reports — cash, equity, ROI, win
rate, drawdown — is derived at read time from these rows and from
`token_market_snapshots`.

Nothing here stores a price, a balance, or a strategy definition:

* prices already live in `token_market_snapshots`, and a second copy could
  disagree with the first;
* a stored balance is a second source of truth that drifts from its positions
  the moment one write lands without the other;
* strategies are code in `app/paper/strategy.py`, published through the API — a
  row describing a rule could disagree with the rule that produced the trades,
  and a reader would have no way to tell which one was applied.

Two constraints carry product meaning rather than hygiene:

* `uq_paper_positions_wallet_mint` is the published entry rule expressed as a
  constraint. The strategy buys a token the **first** time it reaches the top
  ten, so re-entry is not a policy the application enforces — it is a state the
  database cannot represent.
* `uq_paper_wallets_strategy` stops two wallets running the same rules, which
  would double every trade and halve every reported figure.

`ix_paper_positions_open_watermark` is partial on `status = 'open'`: closed rows
are never re-evaluated and will eventually far outnumber open ones. The
predicate is written as the literal SQL the ORM emits, not as a hand-written
equivalent — a mismatch there is silently never used (see CLAUDE.md).

Purely additive. No existing table, column or index is touched, so this applies
while every service runs. Nothing in it connects a wallet or touches a chain.

Revision ID: 0011_paper_wallet
Revises: 0010_outcomes
Create Date: 2026-08-04 13:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_paper_wallet"
down_revision: str | None = "0010_outcomes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "paper_wallets",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("strategy_id", sa.String(length=64), nullable=False),
        sa.Column("strategy_version", sa.String(length=32), nullable=False),
        sa.Column("starting_balance", sa.Numeric(precision=24, scale=4), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paper_wallets")),
        sa.UniqueConstraint("strategy_id", name="uq_paper_wallets_strategy"),
    )
    op.create_index(
        "ix_paper_wallets_created_at", "paper_wallets", ["created_at"], unique=False
    )

    op.create_table(
        "paper_positions",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("wallet_id", sa.UUID(), nullable=False),
        sa.Column("mint_address", sa.String(length=44), nullable=False),
        sa.Column("token_id", sa.UUID(), nullable=True),
        # --- written once at entry, never updated ---
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_rank", sa.Integer(), nullable=False),
        sa.Column("entry_price", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("size_usd", sa.Numeric(precision=24, scale=4), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=48, scale=18), nullable=False),
        sa.Column("target_price", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("stop_price", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        # --- moved by the evaluator ---
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("peak_price", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_price", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("exit_reason", sa.String(length=16), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["token_id"],
            ["discovered_tokens.id"],
            name=op.f("fk_paper_positions_token_id_discovered_tokens"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["wallet_id"],
            ["paper_wallets.id"],
            name=op.f("fk_paper_positions_wallet_id_paper_wallets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paper_positions")),
        sa.UniqueConstraint(
            "wallet_id", "mint_address", name="uq_paper_positions_wallet_mint"
        ),
    )
    op.create_index(
        "ix_paper_positions_closed_at",
        "paper_positions",
        ["wallet_id", "closed_at"],
        unique=False,
    )
    op.create_index(
        "ix_paper_positions_created_at", "paper_positions", ["created_at"], unique=False
    )
    op.create_index(
        "ix_paper_positions_mint", "paper_positions", ["mint_address"], unique=False
    )
    op.create_index(
        "ix_paper_positions_open_watermark",
        "paper_positions",
        ["wallet_id", "last_evaluated_at"],
        unique=False,
        postgresql_where="status = 'open'",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_paper_positions_open_watermark",
        table_name="paper_positions",
        postgresql_where="status = 'open'",
    )
    op.drop_index("ix_paper_positions_mint", table_name="paper_positions")
    op.drop_index("ix_paper_positions_created_at", table_name="paper_positions")
    op.drop_index("ix_paper_positions_closed_at", table_name="paper_positions")
    op.drop_table("paper_positions")
    op.drop_index("ix_paper_wallets_created_at", table_name="paper_wallets")
    op.drop_table("paper_wallets")
