"""The schema the Opportunity Engine depends on.

Two guarantees in this sprint live in the database rather than in code, so they
are asserted against the database. A unit test of the engine would pass with
both constraints missing.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.intelligence import EventKind
from app.opportunities.models import LIVE_STATUSES

pytestmark = pytest.mark.integration


def _migration() -> Any:
    """Load the migration by path.

    Its filename starts with a date, so it is not an importable module name —
    but reading its constants is the point: duplicating them here would let the
    migration and the test drift apart, which is exactly what the drift test
    below is for.
    """
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "20260802_0008_opportunity_engine.py"
    )
    spec = importlib.util.spec_from_file_location("_migration_0008", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_LIVE_STATUSES = _migration()._LIVE_STATUSES
_NEW_EVENT_KINDS = _migration()._NEW_EVENT_KINDS


class TestTables:
    async def test_both_tables_exist(self, db_session: AsyncSession) -> None:
        names = await db_session.run_sync(lambda sync: inspect(sync.bind).get_table_names())
        assert "opportunities" in names
        assert "opportunity_signals" in names

    async def test_no_token_data_is_duplicated(self, db_session: AsyncSession) -> None:
        """Identity stays in `discovered_tokens`.

        `mint_address` is denormalised for join-free reads — the pattern every
        table here uses — but name, symbol, creator and metadata are not copied.
        """
        columns = await db_session.run_sync(
            lambda sync: {
                column["name"] for column in inspect(sync.bind).get_columns("opportunities")
            }
        )
        assert "token_id" in columns
        assert not columns & {"name", "symbol", "creator_address", "metadata_uri", "slot"}


class TestConstraints:
    async def test_one_live_opportunity_per_token_is_enforced_by_the_database(
        self, db_session: AsyncSession
    ) -> None:
        """AD-09's opportunity half. Application checks are the optimisation;
        this index is the guarantee."""
        indexes = await db_session.run_sync(
            lambda sync: inspect(sync.bind).get_indexes("opportunities")
        )
        live = next(
            index for index in indexes if index["name"] == "uq_opportunities_live_mint"
        )
        assert live["unique"]
        assert live["column_names"] == ["mint_address"]

    async def test_the_live_index_predicate_matches_the_enum(
        self, db_session: AsyncSession
    ) -> None:
        """The index and `LIVE_STATUSES` must not drift.

        Adding a live status without widening the predicate would silently let
        two opportunities exist for one token — the exact bug the index is
        there to prevent, reintroduced by omission.
        """
        assert set(_LIVE_STATUSES) == {status.value for status in LIVE_STATUSES}

        predicate = await db_session.scalar(
            text(
                "SELECT pg_get_expr(indpred, indrelid) FROM pg_index "
                "WHERE indexrelid = 'uq_opportunities_live_mint'::regclass"
            )
        )
        assert predicate is not None
        for status in LIVE_STATUSES:
            assert status.value in predicate

    async def test_duplicate_signals_are_rejected_by_the_database(
        self, db_session: AsyncSession
    ) -> None:
        constraints = await db_session.run_sync(
            lambda sync: inspect(sync.bind).get_unique_constraints("opportunity_signals")
        )
        dedupe = next(
            item for item in constraints if item["name"] == "uq_opportunity_signals_dedupe"
        )
        assert dedupe["column_names"] == ["opportunity_id", "signal_type", "provider_id"]

    async def test_generation_is_scoped_per_token(self, db_session: AsyncSession) -> None:
        constraints = await db_session.run_sync(
            lambda sync: inspect(sync.bind).get_unique_constraints("opportunities")
        )
        names = {item["name"]: item["column_names"] for item in constraints}
        assert names["uq_opportunities_mint_gen"] == ["mint_address", "generation"]

    async def test_signals_cascade_from_their_opportunity(
        self, db_session: AsyncSession
    ) -> None:
        """A deleted opportunity must not strand its signals."""
        keys = await db_session.run_sync(
            lambda sync: inspect(sync.bind).get_foreign_keys("opportunity_signals")
        )
        parent = next(key for key in keys if key["referred_table"] == "opportunities")
        assert parent["options"].get("ondelete") == "CASCADE"


class TestEventKinds:
    async def test_every_new_kind_exists_in_the_database_enum(
        self, db_session: AsyncSession
    ) -> None:
        """`event_kind` is a native Postgres enum, so a value the model knows
        about but the type does not is a runtime failure, not a type error."""
        stored = set(
            (
                await db_session.scalars(
                    text("SELECT unnest(enum_range(NULL::event_kind))::text")
                )
            ).all()
        )
        assert set(_NEW_EVENT_KINDS) <= stored

    async def test_the_model_and_the_migration_agree(self) -> None:
        model_kinds = {kind.value for kind in EventKind}
        assert set(_NEW_EVENT_KINDS) <= model_kinds

    async def test_existing_kinds_are_preserved(self, db_session: AsyncSession) -> None:
        """Additive only. Every kind that existed keeps its meaning, and a
        removed value would break `intelligence_events` rows already written.
        """
        stored = set(
            (
                await db_session.scalars(
                    text("SELECT unnest(enum_range(NULL::event_kind))::text")
                )
            ).all()
        )
        assert {
            "mission_promoted",
            "risk_increased",
            "first_analysed",
            "liquidity_improved",
            "confidence_increased",
        } <= stored
