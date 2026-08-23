"""Discovery-engine persistence. **Three tables, all inside the namespace.**

Separate from `strategy_lab_*` proper because a search is a different object
from a wallet: a run holds thousands of definitions that were evaluated and
mostly discarded, and none of them ever holds capital. Filing them in
`strategy_lab_wallets` would put 1,850 hypothetical books beside twelve real
research wallets and invite the leaderboard to average them.

Nothing here has a foreign key outside its own three tables. Nothing here is
ever written by a wallet, and nothing here can be read into one.

**Scalars are duplicated out of `metrics`** on `strategy_lab_discovery_results`
— `n`, `return_pct`, `profit_factor`, `score` and the rest exist both as
columns and inside the JSONB. That is deliberate: the columns are what the
leaderboard sorts and filters on, and sorting 1,850 rows through a JSONB
extraction on every page load is the kind of thing that is fine until it is
not. The JSONB remains the complete record.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_MONEY = Numeric(24, 4)
_PCT = Numeric(14, 4)


class StrategyLabDiscoveryRun(Base):
    """One search. Its dataset, its split, and what came out of the funnel."""

    __tablename__ = "strategy_lab_discovery_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    #: `LOCAL_BACKTEST` or `PRODUCTION_FORWARD_RESEARCH`. §31: the two are
    #: different databases and must never be pooled or compared as one.
    dataset_source: Mapped[str] = mapped_column(String(32), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(16), nullable=False)
    space_version: Mapped[str] = mapped_column(String(16), nullable=False)
    scoring_version: Mapped[str] = mapped_column(String(16), nullable=False)
    canonical_version: Mapped[str] = mapped_column(String(16), nullable=False)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    runtime_seconds: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    schedule_resolutions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    universe_usable: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    exclusions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    #: Granularity, boundaries and block sizes, plus the diagnosis' warnings —
    #: without which a split's percentages mean nothing.
    split: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    funnel: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    search_space: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    attribution: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_sl_discovery_runs_started", "started_at"),)


class StrategyLabDiscoveryCandidate(Base):
    """One generated definition, frozen. Immutable once it has a result."""

    __tablename__ = "strategy_lab_discovery_candidates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("strategy_lab_discovery_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    strategy_id: Mapped[str] = mapped_column(String(24), nullable=False)
    version: Mapped[str] = mapped_column(String(16), nullable=False)
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: The canonical dict the hash was taken over.
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    #: §29. Plain English, stored rather than rendered, so the explanation a
    #: reader saw is the one the run produced.
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    #: The design levels, for §30's attribution and for UI filtering.
    factors: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    entry_size_usd: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    #: GENERATED / DISCOVERY / VALIDATION / HOLDOUT / CHAMPION / FAILED.
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    #: True for the legacy $100 rows. Ranked alongside, never a "discovery".
    reference: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("run_id", "strategy_id", name="uq_sl_discovery_candidate"),
        Index("ix_sl_discovery_candidates_status", "run_id", "status"),
    )


class StrategyLabDiscoveryResult(Base):
    """One candidate's result on one block. `metrics` is the complete record."""

    __tablename__ = "strategy_lab_discovery_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("strategy_lab_discovery_candidates.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: DISCOVERY / VALIDATION / HOLDOUT / WALK_FORWARD.
    block: Mapped[str] = mapped_column(String(16), nullable=False)

    n: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    offered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    capture_pct: Mapped[Decimal | None] = mapped_column(_PCT)
    final_equity: Mapped[Decimal | None] = mapped_column(_MONEY)
    return_pct: Mapped[Decimal | None] = mapped_column(_PCT)
    profit_factor: Mapped[Decimal | None] = mapped_column(_PCT)
    expectancy: Mapped[Decimal | None] = mapped_column(_MONEY)
    max_drawdown_pct: Mapped[Decimal | None] = mapped_column(_PCT)
    win_rate_pct: Mapped[Decimal | None] = mapped_column(_PCT)
    rug_loss_usd: Mapped[Decimal | None] = mapped_column(_MONEY)
    score: Mapped[Decimal | None] = mapped_column(_PCT)
    survives: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    flags: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    #: Robustness, moonshot retention, rug economics, daily consistency,
    #: refusal breakdown and the score components. Everything §14-§20 asks for.
    metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("candidate_id", "block", name="uq_sl_discovery_result_block"),
        Index("ix_sl_discovery_results_block_score", "block", "score"),
    )
