"""Operator-invoked database maintenance: `python -m app.db.maintenance`.

Deliberately **not** scheduled. Nothing in Celery Beat calls this and nothing
should: `VACUUM` on `token_score_history` rewrites 1.8 GB, and a background job
that decides on its own to do that during a launch burst is a worse outage than
the one it prevents. Migration 0007 sets the autovacuum parameters that keep the
statistics honest from here; this command is the one-off catch-up and the escape
hatch for when an operator wants it now.

Two levels, because they cost very different amounts:

    python -m app.db.maintenance            # ANALYZE — seconds, no rewrite
    python -m app.db.maintenance --vacuum   # VACUUM ANALYZE — minutes, rewrites

`ANALYZE` alone is what fixes a bad plan. It samples rows and updates
`pg_class.reltuples` and the column statistics; it takes no lock that blocks
reads or writes. Reach for `--vacuum` only when reclaiming space from dead
tuples, which on these append-only tables is rare. Neither form takes an
`ACCESS EXCLUSIVE` lock, so both are safe on a live system — but only `ANALYZE`
is safe to run without thinking about it first.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

from sqlalchemy import text

from app.core.logging import configure_logging, get_logger
from app.db.session import dispose_engine, engine

logger = get_logger(__name__)

#: The tables whose statistics actually drive plan choice. Every one of them is
#: large enough that a wrong row estimate changes the plan rather than merely
#: the cost. Ordered cheapest-first so an interrupted run has still done the
#: small ones.
MAINTAINED_TABLES = (
    "token_scores",
    "discovered_tokens",
    "token_enrichment_state",
    "token_score_history",
    "token_market_snapshots",
)


async def maintain(
    *, vacuum: bool = False, tables: tuple[str, ...] = MAINTAINED_TABLES
) -> int:
    """Run ANALYZE (or VACUUM ANALYZE) over each table in turn.

    One statement per table rather than a bare database-wide `ANALYZE`, so a
    failure names the table it failed on and progress is visible while a long
    run is in flight.

    Returns the number of tables successfully maintained.
    """
    command = "VACUUM (ANALYZE)" if vacuum else "ANALYZE"
    completed = 0

    # AUTOCOMMIT: VACUUM cannot run inside a transaction block, and ANALYZE in
    # one holds its snapshot open for the whole run for no benefit.
    async with engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        for table in tables:
            started = time.monotonic()
            # Table names come from the module-level tuple, never from user
            # input — identifiers cannot be parameterised, so the safety here
            # is that there is no untrusted path to this string.
            await autocommit.execute(text(f"{command} {table}"))
            completed += 1
            logger.info(
                "maintenance_completed",
                table=table,
                command=command,
                seconds=round(time.monotonic() - started, 2),
            )

    return completed


async def statistics_drift(
    tables: tuple[str, ...] = MAINTAINED_TABLES,
) -> list[dict[str, object]]:
    """What the planner believes about each table, against the truth.

    The number that matters is `pg_class.reltuples` — the planner reads that,
    not `pg_stat_user_tables.n_live_tup`. They can disagree, and during the
    incident this command was written for, they did.

    Read-only. This is the check an operator runs *before* deciding whether
    maintenance is worth its cost, and after, to confirm it worked.
    """
    report: list[dict[str, object]] = []
    async with engine.connect() as connection:
        for table in tables:
            estimate = await connection.scalar(
                text("SELECT reltuples::bigint FROM pg_class WHERE relname = :name"),
                {"name": table},
            )
            # The suppression below is justified: an identifier cannot be
            # parameterised, and `table` is only ever an element of
            # MAINTAINED_TABLES — argparse rejects anything else first.
            actual = await connection.scalar(
                text(f"SELECT count(*) FROM {table}")  # noqa: S608
            )
            estimated = int(estimate or 0)
            true_count = int(actual or 0)
            # A table the planner thinks is empty is the worst case and would
            # divide by zero; report it as the largest possible drift instead.
            ratio = (true_count / estimated) if estimated else float("inf")
            report.append(
                {
                    "table": table,
                    "planner_estimate": estimated,
                    "actual": true_count,
                    "drift_factor": round(ratio, 2) if estimated else None,
                }
            )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.db.maintenance",
        description="Refresh planner statistics. ANALYZE by default.",
    )
    parser.add_argument(
        "--vacuum",
        action="store_true",
        help="Also VACUUM. Rewrites the table; minutes, not seconds.",
    )
    parser.add_argument(
        "--table",
        action="append",
        dest="tables",
        choices=MAINTAINED_TABLES,
        help="Maintain only this table. Repeatable.",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Report planner estimates against actual counts. Changes nothing.",
    )
    args = parser.parse_args(argv)
    targets = tuple(args.tables) if args.tables else MAINTAINED_TABLES

    configure_logging()

    async def _run() -> int:
        try:
            if args.report:
                for row in await statistics_drift(targets):
                    logger.info("statistics_drift", **row)
                return len(targets)
            logger.info("maintenance_starting", vacuum=args.vacuum, tables=list(targets))
            return await maintain(vacuum=args.vacuum, tables=targets)
        finally:
            await dispose_engine()

    try:
        completed = asyncio.run(_run())
    except Exception as exc:
        logger.error("maintenance_failed", error=str(exc), error_type=type(exc).__name__)
        return 1

    logger.info("maintenance_finished", tables_maintained=completed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
