"""Where the Karthik Paper Wallet's rows live, declared rather than imported.

── WHY THIS FILE EXISTS AT ALL ──────────────────────────────────────────

The wallet and its operator were built on two branches at the same time. The
wallet owns `app/models/karthik.py` and the three `karthik_*` tables; this
module owns the layer that watches them. Importing the wallet's ORM model from
here would mean the operator could not be developed, tested or reviewed until
the wallet's branch merged, and — worse — it would make every later change to
the wallet's model a change that can break the monitor silently.

So the operator declares the **columns it actually reads**, as lightweight
Core tables, and nothing else. Three consequences, all of them wanted:

  1. This file is the complete list of the operator's data dependencies. A
     reader can see in one screen exactly what Karthik touches.
  2. A column renamed on the wallet's side fails here, loudly, at query time,
     with the column name in the error — rather than by quietly reading a
     stale value from somewhere else.
  3. Nothing here can write. There is no ORM session identity, no relationship,
     no cascade; a `Table` with six columns cannot accidentally be flushed.

When the two branches merge, this can be replaced by an import of the real
model. It is deliberately the only file that would have to change.

── THE TABLES MAY NOT EXIST ─────────────────────────────────────────────

On a deployment without the wallet's migration they simply are not there, and
a query against them raises. `exists()` is the guard, and the resolver calls it
before anything else — which is what makes "the operator runs correctly with no
wallet" a real state rather than a crash nobody hit yet.
"""

from __future__ import annotations

from sqlalchemy import (
    Column,
    Connection,
    DateTime,
    MetaData,
    Numeric,
    String,
    Table,
    inspect,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession

#: Its own MetaData, unattached to `Base`. Registering these against the
#: application's metadata would make `create_all` try to create them, and the
#: wallet's own migration is what creates them.
_metadata = MetaData()

_MONEY = Numeric(24, 4)
_PRICE = Numeric(38, 18)
_QUANTITY = Numeric(48, 18)

#: The singleton wallet row. `take_profit_multiple` and `trade_size` are read
#: as *published values* to check fills against — never as instructions.
karthik_wallets = Table(
    "karthik_wallets",
    _metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("name", String(32)),
    Column("starting_capital", _MONEY),
    Column("trade_size", _MONEY),
    Column("take_profit_multiple", Numeric(10, 4)),
    Column("activated_at", DateTime(timezone=True)),
)

#: One row per Track Record admission the wallet saw, with what it decided.
#: This is the record that makes "a missed opportunity" a *measurable* thing
#: rather than an inference from a missing position.
karthik_opportunities = Table(
    "karthik_opportunities",
    _metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("wallet_id", UUID(as_uuid=True)),
    Column("mint_address", String(44)),
    Column("track_record_at", DateTime(timezone=True)),
    Column("decision", String(48)),
    Column("decided_at", DateTime(timezone=True)),
)

karthik_positions = Table(
    "karthik_positions",
    _metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("wallet_id", UUID(as_uuid=True)),
    Column("mint_address", String(44)),
    Column("detected_at", DateTime(timezone=True)),
    Column("track_record_at", DateTime(timezone=True)),
    Column("opened_at", DateTime(timezone=True)),
    Column("entry_price", _PRICE),
    Column("cost_basis", _MONEY),
    Column("quantity", _QUANTITY),
    Column("target_price", _PRICE),
    Column("status", String(16)),
    Column("closed_at", DateTime(timezone=True)),
    Column("exit_price", _PRICE),
    Column("exit_proceeds_usd", _MONEY),
    Column("exit_reason", String(32)),
)

#: The decision values the wallet publishes. Compared against, never produced:
#: the operator's job is to notice a decision it does not recognise, which it
#: can only do if the recognised set is written down.
ENTERED = "entered"
SKIPPED_PREFIX = "skipped_"

#: The exit reasons the wallet's rules can produce. Anything else closing a
#: position is a rule the wallet does not have, which is a §16 defect.
KNOWN_EXIT_REASONS = frozenset({"target_1_25x", "dead_zero"})

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


#: Used by the isolation test. A plain string is enough: the assertion is that
#: this module names no other wallet's table, and the way to check that is to
#: read the names it does declare.
def declared_tables() -> tuple[str, ...]:
    return TABLE_NAMES


__all__ = [
    "ENTERED",
    "KNOWN_EXIT_REASONS",
    "SKIPPED_PREFIX",
    "TABLE_NAMES",
    "declared_tables",
    "exists",
    "karthik_opportunities",
    "karthik_positions",
    "karthik_wallets",
    "text",
]
