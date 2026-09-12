"""graduation lab: fifty paper arms, so `book` needs room for a name

0077 introduced `book` as varchar(16) for two values, 'control' and
'filtered'. The tournament names each arm after what it does —
`C01_symnight_5m`, `X07_tp2_trail30` — because a leaderboard of fifty rows is
unreadable otherwise, and those do not fit.

The two-book A/B is subsumed: its filtered arm survives as `C01_symnight_5m`
and its control as `E05_hold_5m`, with the same rules. Its rows are deleted
along with everything else, because the tournament starts every arm level on
the same graduations and a head start for two of them would be the one thing
the comparison cannot survive.

Revision ID: 0078_grad_tournament
Revises: 0077_grad_paper_ab
"""

from alembic import op
import sqlalchemy as sa

revision = "0078_grad_tournament"
down_revision = "0077_grad_paper_ab"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("grad_paper_positions", "book",
                    type_=sa.String(32), existing_nullable=False,
                    existing_server_default="control")
    # Fifty arms all ask "what is open for me" every tick.
    op.create_index("ix_grad_paper_positions_book_open", "grad_paper_positions",
                    ["book", "closed_at"], unique=False,
                    postgresql_where=sa.text("closed_at IS NULL"))


def downgrade() -> None:
    op.drop_index("ix_grad_paper_positions_book_open",
                  table_name="grad_paper_positions")
    op.execute("DELETE FROM grad_paper_positions WHERE length(book) > 16")
    op.alter_column("grad_paper_positions", "book",
                    type_=sa.String(16), existing_nullable=False,
                    existing_server_default="control")
