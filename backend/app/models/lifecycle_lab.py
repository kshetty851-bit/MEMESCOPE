"""Meme Lifecycle Lab tables — see docs/MEME_LIFECYCLE_LAB.md.

Enumerated values are stored as plain strings carrying the
``app.lifecycle_lab.domain`` ``StrEnum`` values, never as native Postgres
enums: the Lab is a research system whose vocabulary is expected to grow, and a
native enum turns every new event type or source into an
``ALTER TYPE ... ADD VALUE`` migration (the `event_kind` trap in CLAUDE.md).

Three tables are append-only and high-volume — collection runs, raw
observations, portfolio snapshots — and deliberately carry no
``TimestampMixin``. Their rows are never updated, so ``updated_at`` would be
noise, and each already has the timestamp that matters (``retrieved_at``,
``finished_at``, ``at``); a ``created_at`` index on ~600k observation rows a
month is write amplification serving no query. ``token_market_snapshots`` is
the precedent.

Write-once columns (``linked_at``, ``detected_at``, ``retrieved_at``) are
guarded by the repository, which never issues an UPDATE against them: links
and observations are inserted ``ON CONFLICT DO NOTHING``, so a re-run can never
move the moment something became known.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, MappedColumn, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

#: Money. Same precision as every other USD column in the schema.
USD = Numeric(24, 4)
#: Token prices run to 1e-9 and below.
PRICE = Numeric(38, 18)
#: Attention values and fractional returns: counts are integers but
#: normalised values and returns are not.
VALUE = Numeric(38, 8)
#: 0..1 with four places.
CONFIDENCE = Numeric(5, 4)
#: A mint is base58 (≤44), but the Lab's tables are not Solana-specific by
#: construction; 64 matches `pumpfun_social_snapshots`.
MINT = String(64)

MEME_STATUS_TRACKED = "tracked"
MEME_STATUS_ARCHIVED = "archived"


def _meme_fk(*, nullable: bool) -> MappedColumn[Any]:
    return mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("mll_memes.id", ondelete="CASCADE"),
        nullable=nullable,
    )


class MllMeme(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A meme the Lab tracks. Curated by hand; nothing creates one implicitly."""

    __tablename__ = "mll_memes"

    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=MEME_STATUS_TRACKED,
        server_default=MEME_STATUS_TRACKED,
    )
    #: Nothing about this meme before this instant is FORWARD data.
    tracking_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    wikipedia_title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    gdelt_query: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (UniqueConstraint("slug", name="uq_mll_memes_slug"),)


class MllMemeAlias(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "mll_meme_aliases"

    meme_id: Mapped[uuid.UUID] = _meme_fk(nullable=False)
    #: As curated, for display.
    alias: Mapped[str] = mapped_column(String(200), nullable=False)
    #: casefolded, stripped, whitespace collapsed, leading $/# removed — the
    #: matcher's key, and the uniqueness key, so "$PEPE" and "pepe" are one alias.
    alias_normalized: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    #: When the alias became known. Gated like every other fact.
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "meme_id", "alias_normalized", "kind", name="uq_mll_meme_aliases_identity"
        ),
    )


class MllMemeToken(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A meme↔token link: a fact with a time.

    No foreign key to `discovered_tokens`: a link is a claim about a mint, and
    with discovery down the mint may not be enrolled yet. Enrolment follows the
    link (`LifecycleLabRepository.enrol_linked_mints`), never the reverse.
    """

    __tablename__ = "mll_meme_tokens"

    meme_id: Mapped[uuid.UUID] = _meme_fk(nullable=False)
    mint_address: Mapped[str] = mapped_column(MINT, nullable=False)
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(CONFIDENCE, nullable=False)
    #: WRITE-ONCE. A link made after a pump does not exist before it — the
    #: single most important look-ahead guard in the Lab. Re-linking is an
    #: `ON CONFLICT DO NOTHING`, so this can never move.
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    unlinked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: What the matcher saw (the alias, the URL, the handle) — provenance.
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: Who made the link: a matcher version or an operator.
    linked_by: Mapped[str] = mapped_column(String(128), nullable=False)

    __table_args__ = (
        UniqueConstraint("meme_id", "mint_address", name="uq_mll_meme_tokens_meme_mint"),
        # Retention and the cadence pass ask "is this mint linked?".
        Index("ix_mll_meme_tokens_mint", "mint_address"),
    )


class MllCollectionRun(Base, UUIDPrimaryKeyMixin):
    """One collection attempt. Absence is never zero: a source that did not
    answer is a row here with a status and a reason, not a missing number."""

    __tablename__ = "mll_collection_runs"

    source: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    data_class: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    meme_id: Mapped[uuid.UUID | None] = _meme_fk(nullable=True)
    mint_address: Mapped[str | None] = mapped_column(MINT, nullable=True)
    observations_written: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        # Source health: the latest run per source.
        Index("ix_mll_collection_runs_source_finished", "source", text("finished_at DESC")),
        Index(
            "ix_mll_collection_runs_meme_source_finished", "meme_id", "source", "finished_at"
        ),
    )


class MllAttentionObservation(Base, UUIDPrimaryKeyMixin):
    """One raw reading — the source of truth. Features are derived from these
    during replay and never stored as truth."""

    __tablename__ = "mll_attention_observations"

    source: Mapped[str] = mapped_column(String(32), nullable=False)
    metric: Mapped[str] = mapped_column(String(32), nullable=False)
    value_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    data_class: Mapped[str] = mapped_column(String(16), nullable=False)
    source_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: The only timestamp that proves knowledge. Written once.
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_value: Mapped[Decimal] = mapped_column(VALUE, nullable=False)
    normalized_value: Mapped[Decimal | None] = mapped_column(VALUE, nullable=True)
    meme_id: Mapped[uuid.UUID | None] = _meme_fk(nullable=True)
    mint_address: Mapped[str | None] = mapped_column(MINT, nullable=True)
    window_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    query: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    confidence: Mapped[Decimal] = mapped_column(
        CONFIDENCE, nullable=False, default=Decimal("1"), server_default="1"
    )
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    collection_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        # Named explicitly: the convention's name is 67 characters, past
        # Postgres's 63-character identifier limit.
        #
        # DEFERRED because the collector writes a run's observations before
        # the run row itself — the run's `observations_written` is only known
        # once they are in. The constraint is still checked, at commit.
        ForeignKey(
            "mll_collection_runs.id",
            ondelete="SET NULL",
            name="fk_mll_obs_collection_run_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=True,
    )
    #: `Observation.dedupe_key()` — sha256 hex. First write wins: a later
    #: revision of the same GDELT bucket is a different claim made later, and
    #: the record of what was known when is immutable.
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_mll_attention_observations_dedupe_key"),
        Index("ix_mll_obs_meme_retrieved", "meme_id", "retrieved_at"),
        Index("ix_mll_obs_mint_retrieved", "mint_address", "retrieved_at"),
        Index("ix_mll_obs_source_observed", "source", "observed_at"),
    )


class MllMemeEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A detector firing, plus how the market moved around it (timeliness).

    Outcome columns are NULL until measured; NULL is "not measured", and the
    reason, when there is one, is in ``outcome_reasons`` — never a zero.
    """

    __tablename__ = "mll_meme_events"

    meme_id: Mapped[uuid.UUID] = _meme_fk(nullable=False)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    #: The replay instant at which the detector fired. Written once.
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    detector_version: Mapped[str] = mapped_column(String(48), nullable=False)
    mint_address: Mapped[str | None] = mapped_column(MINT, nullable=True)
    divergence_case: Mapped[str | None] = mapped_column(String(8), nullable=True)
    lifecycle_state: Mapped[str | None] = mapped_column(String(24), nullable=True)
    features: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    contains_backfill: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    source_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("mll_backtest_runs.id", ondelete="SET NULL"),
        nullable=True,
    )

    price_before_detection: Mapped[Decimal | None] = mapped_column(PRICE, nullable=True)
    price_at_detection: Mapped[Decimal | None] = mapped_column(PRICE, nullable=True)
    return_5m: Mapped[Decimal | None] = mapped_column(VALUE, nullable=True)
    return_15m: Mapped[Decimal | None] = mapped_column(VALUE, nullable=True)
    return_30m: Mapped[Decimal | None] = mapped_column(VALUE, nullable=True)
    return_1h: Mapped[Decimal | None] = mapped_column(VALUE, nullable=True)
    return_2h: Mapped[Decimal | None] = mapped_column(VALUE, nullable=True)
    return_6h: Mapped[Decimal | None] = mapped_column(VALUE, nullable=True)
    return_24h: Mapped[Decimal | None] = mapped_column(VALUE, nullable=True)
    run_up_before_detection: Mapped[Decimal | None] = mapped_column(VALUE, nullable=True)
    #: Field name → Unavailable reason, for every outcome that is NULL for a
    #: reason rather than merely not measured yet.
    outcome_reasons: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: Set once every horizon has been measured or declared unavailable.
    outcomes_complete_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # Expression index, so meme-level events (mint NULL) dedupe too: NULLs
        # are distinct in a plain unique constraint, which would let a replay
        # insert the same meme-level event every time it ran. Kept in the
        # migration as the same text; alembic does not compare expression
        # indexes, so the two must be edited together.
        Index(
            "uq_mll_meme_events_identity",
            "meme_id",
            "event_type",
            "detected_at",
            "detector_version",
            "mode",
            text("coalesce(mint_address, '')"),
            unique=True,
        ),
        Index("ix_mll_meme_events_meme_detected", "meme_id", "detected_at"),
    )


class MllExperiment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """The registry. Every backtest belongs to one, so every test is counted."""

    __tablename__ = "mll_experiments"

    experiment_key: Mapped[str] = mapped_column(String(128), nullable=False)
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    data_cutoff: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    train_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    train_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    validation_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    validation_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    test_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    test_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    strategy_spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    #: `domain.spec_hash(strategy_spec)`. Any change to the spec is a new spec.
    spec_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    arm: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    split_meaningful: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    split_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("experiment_key", name="uq_mll_experiments_experiment_key"),
        Index("ix_mll_experiments_spec_hash", "spec_hash"),
    )


class MllBacktestRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "mll_backtest_runs"

    experiment_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("mll_experiments.id", ondelete="CASCADE"),
        nullable=False,
    )
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    segment: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    config_spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    #: Hash over the inputs the replay read, so two runs over "the same" data
    #: can be shown to have read the same data.
    input_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trades_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    ending_equity: Mapped[Decimal | None] = mapped_column(USD, nullable=True)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    contains_backfill: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    #: EXPLORATORY-only. Every output of such a run is stamped HINDSIGHT.
    hindsight_links: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_mll_backtest_runs_experiment_started", "experiment_id", "started_at"),
        # The overview's "latest authoritative run".
        Index("ix_mll_backtest_runs_mode_finished", "mode", "finished_at"),
    )


class MllPaperTrade(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A simulated trade. The Lab never trades (`domain.REAL_TRADING`)."""

    __tablename__ = "mll_paper_trades"

    backtest_run_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("mll_backtest_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    trade_key: Mapped[str] = mapped_column(String(128), nullable=False)
    arm: Mapped[str] = mapped_column(String(64), nullable=False)
    meme_id: Mapped[uuid.UUID] = _meme_fk(nullable=False)
    mint_address: Mapped[str] = mapped_column(MINT, nullable=False)
    entry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    size_usd: Mapped[Decimal] = mapped_column(USD, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    entry_fees_usd: Mapped[Decimal] = mapped_column(USD, nullable=False)
    entry_market_cap: Mapped[Decimal | None] = mapped_column(USD, nullable=True)
    entry_liquidity_usd: Mapped[Decimal | None] = mapped_column(USD, nullable=True)
    token_age_seconds: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    age_bucket: Mapped[str] = mapped_column(String(16), nullable=False)
    lifecycle_state: Mapped[str | None] = mapped_column(String(24), nullable=True)
    divergence_case: Mapped[str | None] = mapped_column(String(8), nullable=True)
    entry_reason: Mapped[str] = mapped_column(Text, nullable=False)
    entry_features: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evidence_timeline: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    #: `flat` when liquidity was unknown (bonding curve, ADR 0002).
    cost_model: Mapped[str] = mapped_column(String(16), nullable=False)
    exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_price: Mapped[Decimal | None] = mapped_column(PRICE, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    exit_fees_usd: Mapped[Decimal | None] = mapped_column(USD, nullable=True)
    pnl_usd: Mapped[Decimal | None] = mapped_column(USD, nullable=True)
    return_pct: Mapped[Decimal | None] = mapped_column(VALUE, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    contains_backfill: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    hindsight: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    __table_args__ = (
        UniqueConstraint(
            "backtest_run_id", "mint_address", "entry_at", name="uq_mll_paper_trades_entry"
        ),
        Index("ix_mll_paper_trades_meme_entry", "meme_id", "entry_at"),
    )


class MllPortfolioSnapshot(Base, UUIDPrimaryKeyMixin):
    """The equity curve, one row per decision instant."""

    __tablename__ = "mll_portfolio_snapshots"

    backtest_run_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("mll_backtest_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: NULL when an open position could not be marked — an unmarkable book has
    #: no equity, and reporting cash + cost would invent one.
    equity: Mapped[Decimal | None] = mapped_column(USD, nullable=True)
    cash: Mapped[Decimal] = mapped_column(USD, nullable=False)
    deployed: Mapped[Decimal] = mapped_column(USD, nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(USD, nullable=False)
    unrealized_pnl: Mapped[Decimal | None] = mapped_column(USD, nullable=True)
    open_positions: Mapped[int] = mapped_column(Integer, nullable=False)
    peak_equity: Mapped[Decimal | None] = mapped_column(USD, nullable=True)
    drawdown: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)

    __table_args__ = (
        UniqueConstraint("backtest_run_id", "at", name="uq_mll_portfolio_snapshots_run_at"),
    )


class MllReplayCheckpoint(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """The current resumable state of one forward replay (one row per scope).

    A cache with a proof attached, never a record: deleting a row costs one
    full replay and changes no result. ``app/lifecycle_lab/checkpoint.py``
    decides whether the row may be resumed — versions, config, spec hash and
    the input watermark must all still match. Written in the same transaction
    as the run's trades, snapshots and events, so a checkpoint never exists
    without the rows it was computed alongside; it cascades with its run.
    """

    __tablename__ = "mll_replay_checkpoints"

    #: ``CheckpointScope.key()``: mode | arm | experiment | hindsight.
    scope_key: Mapped[str] = mapped_column(String(256), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    arm: Mapped[str] = mapped_column(String(64), nullable=False)
    experiment_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("mll_experiments.id", ondelete="CASCADE"),
        nullable=False,
    )
    backtest_run_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("mll_backtest_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    replay_version: Mapped[str] = mapped_column(String(48), nullable=False)
    #: SHA-256 of the pure engine modules' source (``checkpoint.ENGINE_MODULES``).
    engine_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    spec_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: The last decision tick folded into ``state``.
    processed_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: ``{meme_id | "*": {kind: "count:sum"}}`` at ``processed_until``.
    input_watermark: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    #: ``ReplayState.to_json()``.
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    #: Size of the serialised state, for the cost model.
    state_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("scope_key", name="uq_mll_replay_checkpoints_scope_key"),
    )
