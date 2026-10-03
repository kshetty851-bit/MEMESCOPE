"""Meme Lifecycle Lab schema: properties `alembic check` cannot see.

Alembic compares columns and plain indexes, but not expression indexes, not
whether a String column is wide enough for the enum values written into it,
and not the alias normaliser the uniqueness key depends on. Each of those
would fail at write time in production rather than in CI.
"""

from __future__ import annotations

import importlib.util
from enum import StrEnum
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import Index, String

from app.lifecycle_lab import domain
from app.lifecycle_lab.repository import normalize_alias
from app.models import Base
from app.models.lifecycle_lab import (
    MllAttentionObservation,
    MllBacktestRun,
    MllCollectionRun,
    MllExperiment,
    MllMemeAlias,
    MllMemeEvent,
    MllMemeToken,
    MllPaperTrade,
)
from app.models.market import TokenMarketCandle

pytestmark = pytest.mark.unit

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20261003_0112_meme_lifecycle_lab.py"
)

MLL_TABLES = {
    "mll_memes",
    "mll_meme_aliases",
    "mll_meme_tokens",
    "mll_collection_runs",
    "mll_attention_observations",
    "mll_meme_events",
    "mll_experiments",
    "mll_backtest_runs",
    "mll_paper_trades",
    "mll_portfolio_snapshots",
}


def _migration() -> ModuleType:
    # Dated filenames are not importable as modules (CLAUDE.md); load by path.
    spec = importlib.util.spec_from_file_location("mll_migration_0112", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_lab_table_is_registered() -> None:
    """A model missing from `app.models` is invisible to autogenerate."""
    assert set(Base.metadata.tables) >= MLL_TABLES
    assert "token_market_candles" in Base.metadata.tables
    assert "token_market_candles_1h" not in Base.metadata.tables


def test_migration_chains_onto_0111() -> None:
    module = _migration()
    assert module.revision == "0112_meme_lifecycle_lab"
    assert module.down_revision == "0111_operator_blocked_reason"


def test_every_created_at_index_is_in_the_migration() -> None:
    """TimestampMixin indexes `created_at`; a migration that forgets it fails
    `alembic check` (CLAUDE.md). Asserted here too so the failure names the
    table."""
    source = _MIGRATION.read_text()
    for name in MLL_TABLES:
        if "created_at" in Base.metadata.tables[name].c:
            assert f'_created_at_index("{name}")' in source, name


def test_the_event_identity_expression_matches_the_migration() -> None:
    """Alembic does not compare expression indexes, so drift between the
    model's coalesce() and the migration's would pass CI and leave the ORM's
    test schema deduping differently from production."""
    index = next(
        i
        for i in MllMemeEvent.__table__.indexes
        if isinstance(i, Index) and i.name == "uq_mll_meme_events_identity"
    )
    assert index.unique
    expression = "coalesce(mint_address, '')"
    assert any(str(e) == expression for e in index.expressions)
    assert expression in _MIGRATION.read_text()


def test_candle_key_separates_resolution_and_source() -> None:
    """A 1-minute GeckoTerminal bar and a derived hourly bar for the same
    mint and bucket are different facts and must not collide."""
    pk = [c.name for c in TokenMarketCandle.__table__.primary_key.columns]
    assert pk == ["mint_address", "resolution_s", "source", "bucket"]


@pytest.mark.parametrize(
    ("column", "enum"),
    [
        (MllCollectionRun.source, domain.Source),
        (MllCollectionRun.status, domain.SourceStatus),
        (MllCollectionRun.data_class, domain.DataClass),
        (MllAttentionObservation.source, domain.Source),
        (MllAttentionObservation.metric, domain.Metric),
        (MllAttentionObservation.value_kind, domain.ValueKind),
        (MllAttentionObservation.data_class, domain.DataClass),
        (MllMemeAlias.kind, domain.AliasKind),
        (MllMemeToken.method, domain.LinkMethod),
        (MllMemeEvent.event_type, domain.EventType),
        (MllMemeEvent.mode, domain.ResearchMode),
        (MllMemeEvent.divergence_case, domain.DivergenceCase),
        (MllMemeEvent.lifecycle_state, domain.LifecycleState),
        (MllExperiment.mode, domain.ResearchMode),
        (MllExperiment.arm, domain.Arm),
        (MllBacktestRun.mode, domain.ResearchMode),
        (MllBacktestRun.segment, domain.SplitSegment),
        (MllPaperTrade.arm, domain.Arm),
        (MllPaperTrade.age_bucket, domain.AgeBucket),
        (MllPaperTrade.lifecycle_state, domain.LifecycleState),
        (MllPaperTrade.divergence_case, domain.DivergenceCase),
        (MllPaperTrade.exit_reason, domain.ExitReason),
    ],
)
def test_string_columns_hold_every_enum_value(column: object, enum: type[StrEnum]) -> None:
    """Enums are stored as strings, not native types, so nothing but this
    test stops a new 60-character arm name from being truncated — or refused —
    on its first write."""
    col_type = column.property.columns[0].type  # type: ignore[attr-defined]
    assert isinstance(col_type, String) and col_type.length is not None
    longest = max(len(member.value) for member in enum)
    assert longest <= col_type.length, f"{enum.__name__}: {longest} > {col_type.length}"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("$PEPE", "pepe"),
        ("#Pepe", "pepe"),
        ("  Pepe   the\tFrog ", "pepe the frog"),
        ("$ ", ""),
        ("Straße", "strasse"),  # casefold, not lower
    ],
)
def test_alias_normalisation(raw: str, expected: str) -> None:
    assert normalize_alias(raw) == expected
