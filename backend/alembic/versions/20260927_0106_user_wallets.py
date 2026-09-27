"""USER 1 … USER 10 replace Jaya, Asha and Apoorva.

Karthik, 2026-09-27: "remove family wallets and give list of 10 wallets in
sequence, just name it USER 1, USER 2 etc". The three old rows go; all three
wallets held 0 SOL and never traded. Ten new rows arrive OFF at $20, like any
switch nobody has set. Irreversible in the same sense as 0105: the old names'
settings are gone and the code that read them went in the same commit.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0106_user_wallets"
down_revision: str = "0105_remove_family_shares"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM real_wallet_family_members "
               "WHERE name IN ('JAYA', 'ASHA', 'APOORVA')")
    members = sa.table("real_wallet_family_members",
                       sa.column("name", sa.String), sa.column("updated_by", sa.String))
    op.bulk_insert(members, [{"name": f"USER{i}", "updated_by": "migration 0106"}
                             for i in range(1, 11)])


def downgrade() -> None:
    # Intentionally irreversible: the old names' settings are gone.
    pass
