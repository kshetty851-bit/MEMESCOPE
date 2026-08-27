"""The Pump.fun admission query must stay driven from the token side.

WHAT THIS PROTECTS
==================

`_pumpfun_candidate_statement` used to rank every row of
`token_market_snapshots` with `row_number() OVER (PARTITION BY mint_address)`
and only afterwards apply the age filter that makes the answer small. Measured
against production on 2026-08-22: 141s, 231s and 348s across three runs, for a
result set of 231 rows. The same statement runs from `pumpfun-radar-scan` every
fifteen minutes, so it was also the largest single consumer of a two-vCPU host.

The replacement filters `discovered_tokens` first — about 22k rows in the six-
to-eight-day window, against 176k mints with any snapshot at all — and takes one
row per survivor through a LATERAL. Measured at 1.5s warm.

EQUIVALENCE WAS PROVEN AGAINST PRODUCTION, NOT ASSERTED HERE
============================================================

Both statements were run inside a single `REPEATABLE READ READ ONLY`
transaction on production, so they saw byte-identical data — necessary, because
enrichment writes continuously and two runs minutes apart legitimately disagree.
Both returned 231 rows with identical mint, snapshot id, pool address,
captured_at, price, liquidity, market cap and 24h volume:

    sha256(old) == sha256(new)

That is the equivalence evidence. What a unit test can add is a guard against
the shape silently regressing, which is what these assertions do.

WHY THE FILTER PLACEMENT IS ASSERTED
====================================

`market_cap` and `liquidity_usd` must be tested *outside* the LATERAL. Moving
them inside changes the meaning from "take the newest snapshot, then check it
clears the floor" to "take the newest snapshot that clears the floor" — which
silently admits a stale row for a token whose latest reading has fallen below
it. Both forms return the same rows on data where nothing has fallen below the
floor, so this is exactly the kind of difference a data-driven test would miss
on a good day and discover during a crash.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.dialects import postgresql

from app.radar.repository import RadarRepository

pytestmark = pytest.mark.unit

PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"


def _sql() -> str:
    statement = RadarRepository(None)._pumpfun_candidate_statement(
        program_id=PROGRAM_ID,
        min_age_days=6,
        max_age_days=8,
        min_market_cap=Decimal("0"),
        min_liquidity=Decimal("0"),
        now=datetime(2026, 8, 22, 15, 0, tzinfo=UTC),
    )
    return str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


def test_the_query_never_ranks_the_whole_snapshot_table() -> None:
    """No window function. This is the regression that cost 348 seconds."""
    sql = _sql().lower()

    assert "row_number()" not in sql
    assert "partition by" not in sql
    assert " over (" not in sql


def test_the_latest_snapshot_comes_from_a_bounded_lateral() -> None:
    sql = _sql().lower()

    assert "join lateral" in sql
    # `LIMIT 1` inside the LATERAL is what turns "read this token's history"
    # into "seek the index and stop", and it is the whole performance argument.
    assert "limit 1" in sql


def test_the_lateral_joins_on_token_id() -> None:
    """`token_id` rather than `mint_address`: same answer, narrower index.

    `ix_snapshots_token_captured_desc` is 201MB against the mint index's 383MB,
    and on a host whose page cache holds a fraction of the database that
    difference measured 11.3s versus 1.5s warm.
    """
    sql = _sql().lower()

    assert "token_market_snapshots.token_id = discovered_tokens.id" in sql


def test_the_market_floors_are_applied_outside_the_lateral() -> None:
    """Filter the newest row; do not search for the newest row that passes."""
    sql = _sql().lower()

    lateral_body_start = sql.index("join lateral")
    lateral_body_end = sql.index(") as latest_snapshot", lateral_body_start)
    lateral_body = sql[lateral_body_start:lateral_body_end]
    after_lateral = sql[lateral_body_end:]

    assert "market_cap" not in lateral_body.split("where")[-1].split("order by")[0]
    assert "latest_snapshot.market_cap >=" in after_lateral
    assert "latest_snapshot.liquidity_usd >=" in after_lateral


def test_the_age_window_still_bounds_discovered_tokens() -> None:
    """The selective predicate has to survive; it is why the rewrite is fast."""
    sql = _sql().lower()

    assert "discovered_tokens.block_time >=" in sql
    assert "discovered_tokens.block_time <=" in sql
    assert "discovered_tokens.block_time is not null" in sql
    assert f"discovered_tokens.source_program = '{PROGRAM_ID.lower()}'" in sql


def test_the_result_order_is_unchanged() -> None:
    """Newest observation first, as the shipped query returned."""
    sql = _sql().lower()

    assert sql.rstrip().endswith("order by latest_snapshot.captured_at desc")
