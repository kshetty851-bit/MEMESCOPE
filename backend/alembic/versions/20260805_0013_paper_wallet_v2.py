"""Paper Wallet V2: archive the first wallet, and make room for a relaunch.

Sprint 30. The platform relaunches its simulation with fresh capital under one
published rule. Three things have to become representable for that to be honest:

1. **A wallet is a generation, not a singleton.** `uq_paper_wallets_strategy`
   made a reset impossible to express — archiving a wallet and starting another
   one is precisely what this sprint does, and under the old constraint the only
   way to do it was to delete trades. So identity moves to
   `(strategy_id, generation)`, and `uq_paper_wallets_live` — a unique index on a
   constant, partial on `archived_at IS NULL` — keeps exactly one wallet live at
   a time. "The only wallet users see" becomes a fact the database enforces
   rather than a promise the application makes.

2. **The relaunched rule has no target, no fixed stop and no expiry.** Those
   three columns become nullable. A zero would read as a rule that exists and
   sits at zero; NULL says there is no such rule. Generation-1 rows keep every
   figure they were written with — this migration writes no position column.

3. **Completed trades get a permanent audit row.** `paper_trade_audit` records
   what was observed at each end of a trade, including market cap, pool depth,
   fee and price impact. Those inputs live in `token_market_snapshots`, which is
   pruned, so a figure that was merely derivable would decay to "unavailable"
   for the oldest trades first — exactly the ones a track record is judged on.

**The archive step is data, and it belongs here.** Every existing wallet is
marked archived with its reason. That is not tidying: `uq_paper_wallets_live`
cannot admit the new wallet while the old one is still live, so the archive is
what makes the constraint satisfiable. Nothing is deleted, no position is
touched, and no figure already published is restated — the archived wallet
still reports exactly what it always did, through the internal comparison view.

`generation`, `started_at` and `archived_at` are backfilled from `created_at`,
so the first wallet's own start timestamp remains the one it actually had.

Revision ID: 0013_paper_wallet_v2
Revises: 0012_priority_lane
Create Date: 2026-08-05 09:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_paper_wallet_v2"
down_revision: str | None = "0012_priority_lane"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Printed by the internal comparison view, so it is written once here rather
#: than composed at read time from a status flag.
ARCHIVE_REASON = (
    "Superseded by the Sprint 30 relaunch. This wallet ran Equal Weight v1 "
    "(+100% target, -50% stop, 48-hour hold) and is retained unchanged for "
    "internal historical comparison. Its trades are never mixed into the live "
    "wallet's figures."
)


def upgrade() -> None:
    # --- 1. A wallet becomes a generation ------------------------------------

    op.add_column(
        "paper_wallets",
        sa.Column("generation", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "paper_wallets",
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.add_column(
        "paper_wallets", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("paper_wallets", sa.Column("archive_reason", sa.Text(), nullable=True))

    # The existing wallet's start is the moment it was created, not the moment
    # this migration ran. Backfilling with `now()` would silently restate the
    # period every figure it published was measured over.
    op.execute("UPDATE paper_wallets SET started_at = created_at")

    # The server default existed only to fill the rows already there. Dropping it
    # keeps the generation an explicit decision at every insert: a wallet that
    # silently defaulted to generation 1 would collide with the original.
    op.alter_column("paper_wallets", "generation", server_default=None)

    # `IF EXISTS` because the downgrade cannot always put this constraint back —
    # two generations may legitimately share a strategy by then — so an upgrade
    # that assumed it was present would fail on any database that had been rolled
    # back and rolled forward again.
    op.execute("ALTER TABLE paper_wallets DROP CONSTRAINT IF EXISTS uq_paper_wallets_strategy")
    op.create_unique_constraint(
        "uq_paper_wallets_strategy_generation", "paper_wallets", ["strategy_id", "generation"]
    )

    # --- 2. Archive every wallet that exists ---------------------------------
    #
    # Before the live-wallet index is created, because the index is what stops
    # two live wallets existing and this is what leaves exactly zero. The new
    # wallet is created by the service on its first pass, with its own
    # `started_at` — the benchmarks start from that same instant.
    op.execute(
        sa.text(
            "UPDATE paper_wallets "
            "SET archived_at = now(), archive_reason = :reason "
            "WHERE archived_at IS NULL"
        ).bindparams(reason=ARCHIVE_REASON)
    )

    op.create_index(
        "uq_paper_wallets_live",
        "paper_wallets",
        [sa.text("(true)")],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )

    # --- 3. The trailing-stop position shape ---------------------------------

    op.alter_column(
        "paper_positions", "target_price", existing_type=sa.NUMERIC(38, 18), nullable=True
    )
    op.alter_column(
        "paper_positions", "stop_price", existing_type=sa.NUMERIC(38, 18), nullable=True
    )
    op.alter_column(
        "paper_positions",
        "expires_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )
    op.add_column(
        "paper_positions",
        sa.Column("trailing_drawdown", sa.Numeric(precision=6, scale=4), nullable=True),
    )
    op.add_column(
        "paper_positions",
        sa.Column("entry_market_cap", sa.Numeric(precision=24, scale=4), nullable=True),
    )
    op.add_column(
        "paper_positions",
        sa.Column("entry_liquidity_usd", sa.Numeric(precision=24, scale=4), nullable=True),
    )

    # --- 4. The permanent audit log ------------------------------------------

    op.create_table(
        "paper_trade_audit",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("position_id", sa.UUID(), nullable=False),
        sa.Column("wallet_id", sa.UUID(), nullable=False),
        sa.Column("mint_address", sa.String(length=44), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        # --- entry, as observed ---
        sa.Column("entry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("entry_market_cap", sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column("entry_liquidity_usd", sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column("size_usd", sa.Numeric(precision=24, scale=4), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=48, scale=18), nullable=False),
        # --- exit, as observed ---
        sa.Column("exit_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_price", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("exit_market_cap", sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column("exit_liquidity_usd", sa.Numeric(precision=24, scale=4), nullable=True),
        # --- the result, gross and net ---
        sa.Column("gross_return_usd", sa.Numeric(precision=24, scale=4), nullable=False),
        sa.Column("gross_return_pct", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("fee_usd", sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column("slippage_usd", sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column("net_return_usd", sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column("net_return_pct", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("cost_unavailable_reason", sa.Text(), nullable=True),
        # --- which rule did this ---
        sa.Column("exit_reason", sa.String(length=16), nullable=False),
        sa.Column("strategy_id", sa.String(length=64), nullable=False),
        sa.Column("strategy_version", sa.String(length=32), nullable=False),
        sa.Column("wallet_generation", sa.Integer(), nullable=False),
        sa.Column("swap_fee_bps", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # RESTRICT, not CASCADE. The audit outlives convenience: removing a
        # position that has been audited must be a deliberate act against a
        # refusal, never a side effect of tidying another table.
        sa.ForeignKeyConstraint(
            ["position_id"],
            ["paper_positions.id"],
            name=op.f("fk_paper_trade_audit_position_id_paper_positions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["wallet_id"],
            ["paper_wallets.id"],
            name=op.f("fk_paper_trade_audit_wallet_id_paper_wallets"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paper_trade_audit")),
        # One row per position, ever. A repeated close is a no-op rather than a
        # second entry in the permanent record.
        sa.UniqueConstraint("position_id", name="uq_paper_trade_audit_position"),
    )
    op.create_index(
        "ix_paper_trade_audit_created_at", "paper_trade_audit", ["created_at"], unique=False
    )
    op.create_index(
        "ix_paper_trade_audit_mint", "paper_trade_audit", ["mint_address"], unique=False
    )
    op.create_index(
        "ix_paper_trade_audit_wallet_exit",
        "paper_trade_audit",
        ["wallet_id", "exit_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drops what this migration added. **Two things it deliberately does not do.**

    It does not un-archive. That would have to pick one wallet to make live
    again, and after a relaunch there are two candidates with different capital
    and different trades — guessing would silently merge two track records.

    It does not restore `uq_paper_wallets_strategy` or the NOT NULL on
    target/stop/expiry. Both would fail against data this sprint made legal: two
    generations can share a strategy, and a trailing-stop position has no target.
    A downgrade that crashes halfway is worse than one that stops short and says
    which guarantees it could not put back.
    """
    op.drop_index("ix_paper_trade_audit_wallet_exit", table_name="paper_trade_audit")
    op.drop_index("ix_paper_trade_audit_mint", table_name="paper_trade_audit")
    op.drop_index("ix_paper_trade_audit_created_at", table_name="paper_trade_audit")
    op.drop_table("paper_trade_audit")

    op.drop_column("paper_positions", "entry_liquidity_usd")
    op.drop_column("paper_positions", "entry_market_cap")
    op.drop_column("paper_positions", "trailing_drawdown")
    # Rows written by the relaunched wallet carry no target, stop or expiry, so
    # the columns cannot be made NOT NULL again without inventing values. They
    # stay nullable; the constraint is not restorable and pretending otherwise
    # would fail mid-downgrade on a live database.
    op.drop_index(
        "uq_paper_wallets_live",
        table_name="paper_wallets",
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.drop_constraint("uq_paper_wallets_strategy_generation", "paper_wallets", type_="unique")
    op.drop_column("paper_wallets", "archive_reason")
    op.drop_column("paper_wallets", "archived_at")
    op.drop_column("paper_wallets", "started_at")
    op.drop_column("paper_wallets", "generation")
