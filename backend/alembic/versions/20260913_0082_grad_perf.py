"""graduation lab: an index for the pair-switch check

`switched_mints` asks whether any mint has been sampled against two pool
addresses, which is a pass over every sample ever recorded — measured at
2,269 ms against 56,000 rows, on a table growing 130,000 a day, and it ran on
every status poll.

The answer is now memoised for five minutes in-process, which is the real fix:
the set can only grow from rows written BEFORE the sampler began pinning the
pair, and pinning means it should never grow again. This index is the backstop
for the one call in five minutes that still pays for it — it takes the query
from a sequential scan to an index-only scan, 2,269 ms to 1,099 ms. It cannot
do better than that, because the question has to look at every mint however it
is indexed.

Re-parented from 0079 onto 0081: another session numbered its own migration
0080 against the same parent, which is an alembic BRANCH — two heads, and
`upgrade head` refuses to choose. This one only creates an index, so the order
between the two is arbitrary and chaining behind theirs costs nothing.

Revision ID: 0082_grad_perf
Revises: 0081_rafiq_lab_candidates
"""

from alembic import op

revision = "0082_grad_perf"
down_revision = "0081_rafiq_lab_candidates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_grad_postgrad_mint_pair", "grad_postgrad_samples",
                    ["mint", "pair_address"], unique=False,
                    if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_grad_postgrad_mint_pair",
                  table_name="grad_postgrad_samples", if_exists=True)
