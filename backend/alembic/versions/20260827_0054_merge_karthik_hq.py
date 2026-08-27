"""Rejoin karthik-hq and main, which forked at 0043 and both numbered from 0044.

An empty migration on purpose. It changes no schema; it exists so the history
has ONE head again and `alembic upgrade head` has somewhere to go.

WHAT FORKED. `0043_hq_ops` is the branchpoint. Both sides then wrote their own
0044, 0045 and 0046 — the same numbers for entirely different migrations:

    karthik-hq  0044_paper_wallet_v2 -> 0045_strategy_lab -> 0046_strategy_lab_discovery
    main        0044_karthik_wallet  -> 0045_v4_phase2    -> 0046_rpc_provenance
                -> 0047_quote_checkpoints -> 0048_forward_arena -> 0049_v6_strategy_lab
                -> 0050_autotrade_switch -> 0051_password_reset
                -> 0052_real_position_exit_state -> 0053_wallet_balance_observations

WHY A MERGE IS SAFE HERE, rather than a rebase or a rewrite. Every migration on
both chains is additive — each one says "N new tables, and nothing else" or
"Additive only" in its own docstring, and none alters or drops an existing
table. Two additive chains cannot disagree about a column, so joining them
needs no reconciliation, only a single point they both lead to.

WHAT THIS DOES NOT DO. It does not apply either chain. A database sitting on
one branch still has to run the other branch's migrations to reach this
revision, and on a database with real data that is a deliberate act, not a
side effect of a code merge. Nothing here is reversible by `downgrade -1`
either: stepping back from a merge point goes down ONE parent, and which one
is not the question anybody means to be asking.
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0054_merge_karthik_hq"
down_revision: tuple[str, str] = (
    "0046_strategy_lab_discovery",
    "0053_wallet_balance_observations",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No schema change. See the module docstring."""


def downgrade() -> None:
    """No schema change. See the module docstring."""
