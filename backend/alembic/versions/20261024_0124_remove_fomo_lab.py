"""Remove the FOMO Lab.

Deleted at Karthik's request on 2026-10-24 ("delete fomo lab"): code, page, nav,
scheduled tasks and the records, in one commit, like `0110`. Only FOMO's own
tables reference each other (checked on production); CASCADE takes those links.

Intentionally irreversible: `0121`/`0122` stay in the chain as history.
"""

from __future__ import annotations

from alembic import op

revision: str = "0124_remove_fomo_lab"
down_revision: str = "0123_longwatch_lab"
branch_labels = None
depends_on = None

TABLES = ("fomo_signals", "fomo_positions", "fomo_leaders", "fomo_books")


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")


def downgrade() -> None:
    raise NotImplementedError("0124 deletes the FOMO Lab's records; restore from a backup")
