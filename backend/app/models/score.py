"""AI scoring models.

Two tables with different access patterns, split for the same reasons the market
tables are (see `app/models/market.py`):

  * `token_scores` is the mutable current state - exactly one row per token,
    upserted on every evaluation. It is deliberately **narrow**: only scalars
    live here, so the hot write path rewrites ~150 bytes rather than a
    multi-kilobyte JSONB document on every refresh.
  * `token_score_history` is append-only and carries the expensive detail (the
    per-component breakdown and reason codes). It is written only when a score
    changes materially, which is a small fraction of evaluations.

Three columns that an earlier draft of the design carried here are deliberately
absent, and their absence is load-bearing:

  * `confidence` - it decays with wall-clock time, so a stored value is stale the
    moment it is written. `evidence` (time-invariant) is stored instead and
    freshness is applied at read time.
  * `previous_score` / `elite_streak` - read-modify-write columns with three
    concurrent writers (inline scoring, the sweep, and rescore jobs). Both are
    derived from `token_score_history` instead.

See docs/AI_SCORING_DESIGN.md §11 for the full rationale.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.token import PUBKEY_MAX_LENGTH, DiscoveredToken

# Scores are bounded 0.00-100.00. Numeric rather than float so a value survives
# the round trip exactly: golden-file tests compare 71.40 to 71.40, never to
# 71.40000000000001.
SCORE_PRECISION = Numeric(5, 2)

# Evidence floor baked into the `ranking_hot` partial index. It mirrors the
# `min_evidence` default on the ranking endpoint; the two must move together,
# which is why the value lives here as a named constant rather than inline.
RANKING_HOT_MIN_EVIDENCE = 25

MODEL_VERSION_MAX_LENGTH = 32
TRIGGER_MAX_LENGTH = 32


class ScoreGrade(enum.StrEnum):
    """Discrete band shown in the UI.

    Bands exist so the product has a stable label to render: a score moving
    68.2 → 69.1 should not look like news. Boundaries are a product decision
    (design §21.1, open question 3), and adding a value later needs
    `ALTER TYPE ... ADD VALUE`, which is why they are settled before ship.
    """

    CRITICAL = "critical"
    WEAK = "weak"
    WATCH = "watch"
    STRONG = "strong"
    HIGH_CONVICTION = "high_conviction"


class ScoreTrigger(enum.StrEnum):
    """Why a history row was written.

    Stored as a plain string column rather than a native enum, matching
    `TokenEnrichmentState.tier`: these are diagnostic labels for a set expected
    to grow, and a migration per added value is not worth the type safety here.
    """

    FIRST = "first"
    DELTA = "delta"
    GRADE_CHANGE = "grade_change"
    ELITE_CHANGE = "elite_change"
    VETO_CHANGE = "veto_change"
    HEARTBEAT = "heartbeat"


# One shared type object for both tables. Binding it to the metadata (rather
# than declaring it per column) means the Postgres type is created once, before
# either table - two independent `Enum(...)` declarations with the same name
# would race to CREATE TYPE during create_all.
SCORE_GRADE = Enum(
    ScoreGrade,
    name="score_grade",
    native_enum=True,
    validate_strings=True,
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
    metadata=Base.metadata,
)


def _bounded(column: str) -> CheckConstraint:
    """0-100 guard for a score-like column.

    Cheap insurance at the boundary. The engine asserts these ranges too, but a
    bad backfill or a hand-written UPDATE bypasses the engine entirely, and a
    score of 240 rendered as a percentage is the kind of defect that erodes
    trust in every other number on the page.
    """
    return CheckConstraint(f"{column} >= 0 AND {column} <= 100", name=f"{column}_range")


class TokenScore(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Current score for one token. Exactly one row per discovered token."""

    __tablename__ = "token_scores"

    token_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("discovered_tokens.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    # Denormalised so lookups and rankings never join back to the token.
    mint_address: Mapped[str] = mapped_column(
        String(PUBKEY_MAX_LENGTH), unique=True, index=True, nullable=False
    )

    # Which weight vector produced this row. Scores from different versions are
    # never comparable, so this is never null and always travels with the score.
    model_version: Mapped[str] = mapped_column(
        String(MODEL_VERSION_MAX_LENGTH), nullable=False
    )

    score: Mapped[Decimal] = mapped_column(SCORE_PRECISION, nullable=False)
    # Time-invariant evidence quality: coverage x depth. The served `confidence`
    # is this value decayed by freshness at read time, and is never stored.
    evidence: Mapped[Decimal] = mapped_column(SCORE_PRECISION, nullable=False)
    coverage: Mapped[Decimal] = mapped_column(SCORE_PRECISION, nullable=False)
    market_risk: Mapped[Decimal] = mapped_column(SCORE_PRECISION, nullable=False)
    # Pre-gate composite. Kept for diagnosis: when a score is low it answers
    # "weak components, or a healthy token punished by the risk gate?".
    opportunity_raw: Mapped[Decimal] = mapped_column(SCORE_PRECISION, nullable=False)

    observations: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    grade: Mapped[ScoreGrade] = mapped_column(SCORE_GRADE, nullable=False)
    is_elite: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    has_veto: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    # Input to read-time freshness. Distinct from `evaluated_at`: a sweep can
    # re-evaluate an old snapshot, which advances the evaluation time without
    # making the underlying data any fresher.
    latest_snapshot_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Also the monotonic-guard key - see `ScoreRepository.upsert_many`.
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Provenance as a timestamp, not a foreign key. An enforced FK into
    # `token_market_snapshots` would block the partition detach/drop that
    # snapshot retention will eventually depend on.
    source_snapshot_captured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    token: Mapped[DiscoveredToken] = relationship(lazy="raise")

    __table_args__ = (
        _bounded("score"),
        _bounded("evidence"),
        _bounded("coverage"),
        _bounded("market_risk"),
        _bounded("opportunity_raw"),
        CheckConstraint("observations >= 0", name="observations_non_negative"),
        # Keyset ranking: ORDER BY score DESC, mint_address ASC within one model
        # version. The tiebreak column is in the index, so paging by cursor is a
        # range scan rather than a sort.
        Index(
            "ix_token_scores_ranking",
            "model_version",
            text("score DESC"),
            "mint_address",
        ),
        # The default filter combination gets its own partial index: excluding
        # vetoed and low-evidence rows removes the bulk of the table, so the
        # common ranking query touches a fraction of the entries.
        Index(
            "ix_token_scores_ranking_hot",
            "model_version",
            text("score DESC"),
            "mint_address",
            postgresql_where=text(
                f"has_veto = false AND evidence >= {RANKING_HOT_MIN_EVIDENCE}"
            ),
        ),
        # Elite is rare by construction, so this partial index stays tiny.
        Index(
            "ix_token_scores_elite",
            text("score DESC"),
            postgresql_where=text("is_elite"),
        ),
        # The sweep's "which scores are stale?" scan.
        Index("ix_token_scores_staleness", "evaluated_at"),
    )


class TokenScoreHistory(Base, UUIDPrimaryKeyMixin):
    """One immutable record of a materially changed score.

    Append-only; nothing updates a row here. Two consumers depend on that: the
    Elite streak is derived by replaying rows in evaluation order, and score
    deltas are computed against the previous row rather than a mutable column.

    No `TimestampMixin` - `evaluated_at` is the only meaningful time, exactly as
    `captured_at` is for market snapshots.
    """

    __tablename__ = "token_score_history"

    token_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("discovered_tokens.id", ondelete="CASCADE"),
        nullable=False,
    )
    mint_address: Mapped[str] = mapped_column(String(PUBKEY_MAX_LENGTH), nullable=False)

    model_version: Mapped[str] = mapped_column(
        String(MODEL_VERSION_MAX_LENGTH), nullable=False
    )

    score: Mapped[Decimal] = mapped_column(SCORE_PRECISION, nullable=False)
    evidence: Mapped[Decimal] = mapped_column(SCORE_PRECISION, nullable=False)
    coverage: Mapped[Decimal] = mapped_column(SCORE_PRECISION, nullable=False)
    market_risk: Mapped[Decimal] = mapped_column(SCORE_PRECISION, nullable=False)
    opportunity_raw: Mapped[Decimal] = mapped_column(SCORE_PRECISION, nullable=False)

    observations: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    grade: Mapped[ScoreGrade] = mapped_column(SCORE_GRADE, nullable=False)
    is_elite: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    has_veto: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    # The expensive payload, kept out of the hot table. Read as a unit and never
    # filtered by component in v1, so a JSONB document rather than N rows; a GIN
    # index can be added later without a schema change if that need appears.
    components: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), nullable=False
    )
    reasons: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), nullable=False
    )

    # Signed change against the previous history row; null on the first row.
    delta: Mapped[Decimal | None] = mapped_column(SCORE_PRECISION, nullable=True)
    trigger: Mapped[str] = mapped_column(String(TRIGGER_MAX_LENGTH), nullable=False)

    latest_snapshot_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    source_snapshot_captured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    token: Mapped[DiscoveredToken] = relationship(lazy="raise")

    __table_args__ = (
        _bounded("score"),
        _bounded("evidence"),
        _bounded("coverage"),
        _bounded("market_risk"),
        _bounded("opportunity_raw"),
        CheckConstraint("observations >= 0", name="observations_non_negative"),
        # The dominant read: "history for this token, newest first". Also serves
        # the single-row lookup that resolves a token's current detail.
        Index("ix_score_history_mint_evaluated", "mint_address", evaluated_at.desc()),
        Index("ix_score_history_evaluated", evaluated_at.desc()),
    )
