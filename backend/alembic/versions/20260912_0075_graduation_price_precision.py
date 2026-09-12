"""graduation lab: eight decimals is not enough for a post-graduation price

A pump.fun token trading below 0.000000005 SOL rounded to ZERO in
`Numeric(24, 8)`, and nothing downstream could tell that from a price. 16,775
samples across 378 mints were stored as 0 while the tokens were still trading
— one had a recorded maximum equal to its own pool-open price.

The paper book marked those positions at zero and closed them at -100%: five
trades, -$500 of a -$258.94 book. Without them the same book is +$241.

So the columns widen to Numeric(36, 18), and the existing zeros become NULL,
which is what they always meant: not "worthless", but "not recorded".

Revision ID: 0075_graduation_price_precision
Revises: 0074_graduation_paper_usd
"""

from alembic import op
import sqlalchemy as sa

revision = "0075_graduation_price_precision"
down_revision = "0074_graduation_paper_usd"
branch_labels = None
depends_on = None

_WIDE = sa.Numeric(36, 18)
_OLD = sa.Numeric(24, 8)
_COLUMNS = (
    ("grad_postgrad_samples", "price_usd"),
    ("grad_postgrad_samples", "price_native"),
)


def upgrade() -> None:
    for table, column in _COLUMNS:
        op.alter_column(table, column, type_=_WIDE, existing_nullable=True)
    # A zero price was never a price. Done AFTER the widen so the rows that
    # still carry a real small value keep it.
    op.execute("""
        UPDATE grad_postgrad_samples
           SET price_native = NULL
         WHERE price_native = 0
    """)
    op.execute("""
        UPDATE grad_postgrad_samples
           SET price_usd = NULL
         WHERE price_usd = 0
    """)


def downgrade() -> None:
    # The NULLs are not restored: the zeros they replaced were wrong, and
    # putting them back would re-create the -100% exits.
    for table, column in _COLUMNS:
        op.alter_column(table, column, type_=_OLD, existing_nullable=True)
