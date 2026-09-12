"""graduation lab: two paper books, an A/B on the entry filter

Replaying 537 graduations found two entry-time signals that separate rugs:
a symbol never seen before rugs inside five minutes 18.0% of the time
against 3.0% for a reused one, and a pool opening 06:00-17:59 UTC rugs 14.9%
against 5.4% for 18:00-05:59. Both held on each of the two recorded days.
Combined they cut the rug rate to 2.0% and keep 47% of graduations — and
the P&L confidence interval still straddles zero on two days of data.

So it is not adopted, it is TESTED: a second book with identical rules plus
the entry filter, run alongside the unfiltered one on the same graduations.
Four weeks later the two are compared on identical tokens. The control stays
exactly as it was frozen.

`book` is 'control' or 'filtered'. The unique key becomes (book, mint): the
same token may appear once in each.

Revision ID: 0077_grad_paper_ab
Revises: 0076_grad_position_precision
"""

from alembic import op
import sqlalchemy as sa

revision = "0077_grad_paper_ab"
down_revision = "0076_grad_position_precision"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("grad_paper_positions",
                  sa.Column("book", sa.String(16), nullable=False,
                            server_default="control"))
    op.drop_constraint("uq_grad_paper_positions_mint", "grad_paper_positions",
                       type_="unique")
    op.create_unique_constraint("uq_grad_paper_positions_book_mint",
                                "grad_paper_positions", ["book", "mint"])
    op.create_index("ix_grad_paper_positions_book", "grad_paper_positions",
                    ["book", "closed_at"])
    # The filtered book asks "how many EARLIER tokens used this symbol" at
    # every fill, against a table that grows by a thousand rows an hour.
    op.create_index("ix_grad_tokens_symbol_lower", "grad_tokens",
                    [sa.text("lower(symbol)"), "first_seen_at"])


def downgrade() -> None:
    op.drop_index("ix_grad_tokens_symbol_lower", table_name="grad_tokens")
    op.drop_index("ix_grad_paper_positions_book", table_name="grad_paper_positions")
    op.drop_constraint("uq_grad_paper_positions_book_mint",
                       "grad_paper_positions", type_="unique")
    op.execute("DELETE FROM grad_paper_positions WHERE book <> 'control'")
    op.create_unique_constraint("uq_grad_paper_positions_mint",
                                "grad_paper_positions", ["mint"])
    op.drop_column("grad_paper_positions", "book")
