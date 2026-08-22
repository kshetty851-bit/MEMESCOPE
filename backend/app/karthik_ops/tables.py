"""Where the Karthik Paper Wallet's rows live.

── WHAT THIS FILE USED TO BE, AND WHY IT CHANGED ────────────────────────

The wallet and its operator were built on two branches at the same time. Until
they merged, this module declared the columns the operator reads as lightweight
Core tables, so the operator could be built, tested and deployed against a
schema whose model it could not yet import.

The branches have merged. This now imports the real model, which is what that
arrangement was always for — it was written to be the single file that changed
here, and it was.

── WHAT IT STILL DOES ───────────────────────────────────────────────────

Two things worth keeping. First, it remains the *complete list of the
operator's data dependencies*: three tables, no relationships, no writes. A
reader can see in one screen exactly what Karthik touches, and the isolation
test reads this list rather than trusting a sentence.

Second, it re-exports the wallet's own vocabulary — the decision strings and
the exit reasons — from `app.karthik.rules`, which is where they are defined.
The operator's job includes noticing a decision it does not recognise, and it
can only do that if "recognised" means the wallet's own enum rather than a
second copy of it that can drift.

── THE TABLES MAY STILL BE ABSENT ───────────────────────────────────────

A deployment that has not run the wallet's migration has no `karthik_*` tables,
and a query against them raises. `exists()` is the guard and the resolver calls
it first, which is what keeps "the operator runs correctly with no wallet" a
real, tested state rather than a crash nobody hit.
"""

from __future__ import annotations

from typing import cast

from sqlalchemy import Connection, Table, inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.karthik.rules import Decision, ExitReason
from app.models.karthik import KarthikOpportunity, KarthikPosition, KarthikWallet

#: The three tables, under the names the read layer uses. Aliased rather than
#: re-exported verbatim so the query sites read as table access rather than as
#: ORM entity access — nothing here is ever added to a session.
# `cast` rather than an annotation: SQLAlchemy declares `__table__` as
# `FromClause` on the mapped-class protocol, and it is a `Table` for every
# declarative model. Narrowing it once here is what lets the query sites and
# the isolation test read `.c` and `.name` without an ignore on each line.
karthik_wallets = cast(Table, KarthikWallet.__table__)
karthik_opportunities = cast(Table, KarthikOpportunity.__table__)
karthik_positions = cast(Table, KarthikPosition.__table__)

#: The wallet's own decision vocabulary, not a copy of it. A decision outside
#: this set means the wallet grew a rule the operator has not been told about,
#: which is worth an owner's attention whichever way it turns out.
#:
#: Derived from the enum rather than matched on a `skipped_` prefix. A prefix
#: rule would silently accept any future string somebody happened to name that
#: way, which is the opposite of what this check is for.
ENTERED = Decision.ENTERED.value
KNOWN_DECISIONS: frozenset[str] = frozenset(decision.value for decision in Decision)

#: The exit reasons the wallet's rules can produce, read from the wallet's own
#: enum. Anything else closing a position is a rule the wallet does not have,
#: which is a §16 defect — and defining this list here rather than importing it
#: would be the operator deciding what the wallet is allowed to do.
KNOWN_EXIT_REASONS: frozenset[str] = frozenset(reason.value for reason in ExitReason)

TABLE_NAMES = (
    karthik_wallets.name,
    karthik_opportunities.name,
    karthik_positions.name,
)


async def exists(session: AsyncSession) -> bool:
    """Are the wallet's tables present on this deployment?

    Asked once per read, through the dialect's own inspector rather than by
    catching an exception from a failed query: a failed query inside a
    transaction poisons it, and the caller would then have to know to roll back
    before doing anything else. A cheap catalogue lookup has no such cost.
    """

    def _check(connection: Connection) -> bool:
        names = set(inspect(connection).get_table_names())
        return all(name in names for name in TABLE_NAMES)

    connection = await session.connection()
    return bool(await connection.run_sync(_check))


def declared_tables() -> tuple[str, ...]:
    """The complete set of rows the operator can reach. Read by the isolation
    test, which asserts there are three of them and that they are all the
    wallet's."""
    return TABLE_NAMES


__all__ = [
    "ENTERED",
    "KNOWN_DECISIONS",
    "KNOWN_EXIT_REASONS",
    "TABLE_NAMES",
    "declared_tables",
    "exists",
    "karthik_opportunities",
    "karthik_positions",
    "karthik_wallets",
]
