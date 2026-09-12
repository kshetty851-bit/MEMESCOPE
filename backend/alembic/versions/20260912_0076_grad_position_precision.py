"""graduation lab: the positions table had the same eight-decimal hole

0075 widened the price columns on `grad_postgrad_samples` and stopped the
recorder writing zeros. It left `grad_paper_positions`, which stores the same
prices at the same `Numeric(24, 8)` — so a position on a token quoted below
0.000000005 SOL still wrote `open_quote`, `peak_quote`, `last_quote` and
`close_quote` as ZERO.

That is worse than it was before 0075, not better: the realised P&L is
computed from the unquantised price and is correct, but 0075 also added a rule
voiding any trade whose `close_quote` is zero. A legitimate trade on a cheap
token was therefore being dropped from the book on the strength of a rounding
artefact in a column that was never read for the P&L.

`alembic_version.version_num` is varchar(32) and the obvious id for this
migration is 34 characters, so it is abbreviated. Anything longer fails at
the very last statement, AFTER the DDL, and the backend crash-loops because
it migrates on startup.

Revision ID: 0076_grad_position_precision
Revises: 0075_graduation_price_precision
"""

from alembic import op
import sqlalchemy as sa

revision = "0076_grad_position_precision"
down_revision = "0075_graduation_price_precision"
branch_labels = None
depends_on = None

_WIDE = sa.Numeric(36, 18)
_OLD = sa.Numeric(24, 8)
_COLUMNS = ("open_quote", "open_fill", "peak_quote", "last_quote",
            "close_quote", "close_fill")


def upgrade() -> None:
    for column in _COLUMNS:
        op.alter_column("grad_paper_positions", column, type_=_WIDE,
                        existing_nullable=column not in ("open_quote",
                                                         "open_fill",
                                                         "peak_quote"))
    # The zeros already written cannot be recovered — the precision is gone.
    # NULL is the honest value for the nullable ones; a zero there is a claim
    # the token was worthless, which is exactly the claim that was wrong.
    op.execute("""
        UPDATE grad_paper_positions
           SET last_quote = NULL
         WHERE last_quote = 0
    """)
    op.execute("""
        UPDATE grad_paper_positions
           SET close_quote = NULL, close_fill = NULL
         WHERE close_quote = 0
    """)


def downgrade() -> None:
    for column in _COLUMNS:
        op.alter_column("grad_paper_positions", column, type_=_OLD,
                        existing_nullable=column not in ("open_quote",
                                                         "open_fill",
                                                         "peak_quote"))
