"""The Karthik paper wallet: three new tables, no existing table touched.

Not one column, index or constraint of `paper_wallets`, `paper_positions`,
`paper_trade_audit`, `radar_tokens` or any real-wallet table is altered here.
That is the requirement, not a coincidence of this change being small: Karthik
is a second experiment running beside the first, and the first's published
figures must be provably unaffected by the second's existence.

In particular `uq_paper_wallets_live` — the unique index that guarantees
exactly one live paper wallet — is left exactly as it was. Karthik does not
need room in that table, because it does not live in it.

`karthik_wallets` gets a singleton unique index of its own, over the constant
expression `(true)`. It says "at most one Karthik wallet, ever", which is what
makes the activation command idempotent at the database rather than in a
runbook: a second activation cannot create a second wallet and therefore cannot
move `activated_at`.

`TimestampMixin` is not used, but `created_at` still needs its index declared on
every table or `alembic check` fails on the next autogenerate.

Revision ID: 0044_karthik_wallet
Revises: 0043_hq_ops
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0044_karthik_wallet"
down_revision = "0043_hq_ops"
branch_labels = None
depends_on = None

_PRICE = sa.Numeric(38, 18)
_MONEY = sa.Numeric(24, 4)
_QUANTITY = sa.Numeric(48, 18)
_PCT = sa.Numeric(20, 4)


def upgrade() -> None:
    op.create_table(
        "karthik_wallets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("starting_capital", _MONEY, nullable=False),
        sa.Column("trade_size", _MONEY, nullable=False),
        sa.Column("take_profit_multiple", sa.Numeric(10, 4), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_karthik_wallets")),
    )
    op.create_index(
        "uq_karthik_wallets_singleton", "karthik_wallets", [sa.text("(true)")], unique=True
    )
    op.create_index("ix_karthik_wallets_created_at", "karthik_wallets", ["created_at"])

    op.create_table(
        "karthik_opportunities",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("wallet_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mint_address", sa.String(length=44), nullable=False),
        sa.Column("track_record_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["wallet_id"],
            ["karthik_wallets.id"],
            name=op.f("fk_karthik_opportunities_wallet_id_karthik_wallets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_karthik_opportunities")),
        # The exactly-once guarantee. One decision per Track Record admission,
        # ever — a duplicate event, a Celery retry and a restarted worker all
        # collapse onto this index.
        sa.UniqueConstraint(
            "wallet_id", "mint_address", name="uq_karthik_opportunities_wallet_mint"
        ),
    )
    op.create_index(
        "ix_karthik_opportunities_wallet_seen",
        "karthik_opportunities",
        ["wallet_id", "track_record_at"],
    )
    op.create_index(
        "ix_karthik_opportunities_created_at", "karthik_opportunities", ["created_at"]
    )

    op.create_table(
        "karthik_positions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("wallet_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mint_address", sa.String(length=44), nullable=False),
        sa.Column("token_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("token_name", sa.String(length=128), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("track_record_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", _PRICE, nullable=False),
        sa.Column("entry_observed_price", _PRICE, nullable=False),
        sa.Column("entry_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cost_basis", _MONEY, nullable=False),
        sa.Column("quantity", _QUANTITY, nullable=False),
        sa.Column("decimals", sa.Integer(), nullable=False),
        sa.Column("target_price", _PRICE, nullable=False),
        sa.Column("pool_address", sa.String(length=44), nullable=True),
        sa.Column("entry_liquidity_usd", _MONEY, nullable=True),
        sa.Column("entry_market_cap", _MONEY, nullable=True),
        sa.Column("entry_execution_model_version", sa.String(length=64), nullable=True),
        sa.Column(
            "entry_execution_quote",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("entry_execution_price_impact_pct", _PCT, nullable=True),
        sa.Column("entry_execution_fee_usd", _MONEY, nullable=True),
        sa.Column("entry_execution_route", sa.Text(), nullable=True),
        sa.Column("entry_execution_confidence", sa.String(length=32), nullable=True),
        sa.Column("entry_execution_fallback_reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("peak_price", _PRICE, nullable=False),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_market_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_price", _PRICE, nullable=True),
        sa.Column("exit_observed_price", _PRICE, nullable=True),
        sa.Column("exit_proceeds_usd", _MONEY, nullable=True),
        sa.Column("exit_reason", sa.String(length=16), nullable=True),
        sa.Column("exit_execution_model_version", sa.String(length=64), nullable=True),
        sa.Column(
            "exit_execution_quote", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("exit_execution_price_impact_pct", _PCT, nullable=True),
        sa.Column("exit_execution_fee_usd", _MONEY, nullable=True),
        sa.Column("exit_execution_route", sa.Text(), nullable=True),
        sa.Column("exit_execution_confidence", sa.String(length=32), nullable=True),
        sa.Column("exit_evidence", sa.Text(), nullable=True),
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
            ["wallet_id"],
            ["karthik_wallets.id"],
            name=op.f("fk_karthik_positions_wallet_id_karthik_wallets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["token_id"],
            ["discovered_tokens.id"],
            name=op.f("fk_karthik_positions_token_id_discovered_tokens"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_karthik_positions")),
        # The second half of exactly-once: even a caller that bypassed the
        # opportunity ledger cannot open two Karthik positions in one mint.
        sa.UniqueConstraint(
            "wallet_id", "mint_address", name="uq_karthik_positions_wallet_mint"
        ),
    )
    op.create_index(
        "ix_karthik_positions_open_watermark",
        "karthik_positions",
        ["wallet_id", "last_evaluated_at"],
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index(
        "ix_karthik_positions_closed_at", "karthik_positions", ["wallet_id", "closed_at"]
    )
    op.create_index("ix_karthik_positions_created_at", "karthik_positions", ["created_at"])


def downgrade() -> None:
    op.drop_table("karthik_positions")
    op.drop_table("karthik_opportunities")
    op.drop_table("karthik_wallets")
