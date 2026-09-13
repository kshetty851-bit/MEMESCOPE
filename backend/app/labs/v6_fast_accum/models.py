"""The lab's own tables. Prefix `v6lab_`. `RESEARCH_ONLY`.

On the PLATFORM's `Base`, for the reason every other lab here documents: a
separate metadata makes `alembic revision --autogenerate` emit `drop_table` for
everything it can see in the database and not in the model tree.

Two tables, not the nine the brief sketches. `v6lab_runs` carries the immutable
configuration and the whole result document; `v6lab_trades` carries the
per-trade rows the dashboard needs for exit mix and profit concentration.
Splitting entries, exits and outcomes into their own tables would be three
joins to rebuild one row that is only ever read as one row.

Nothing else in the platform references these, and nothing writes to them
except `runner.persist`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Index, Integer, Numeric, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_RET = Numeric(18, 8)
_USD = Numeric(24, 8)


class V6LabRun(Base):
    """One execution of the experiment. Immutable once written."""

    __tablename__ = "v6lab_runs"
    __table_args__ = (Index("ix_v6lab_runs_started", "started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    #: e.g. V6_FAST_ACCUM_2026_09_13_001
    experiment_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    spec_version: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Digest of every pre-registered value. Two runs sharing it tested the
    #: same hypothesis; a different digest is a different experiment.
    config_hash: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Digest of the ROWS loaded, so a re-run on the same data is checkable.
    dataset_version: Mapped[str] = mapped_column(String(32), nullable=False)
    git_sha: Mapped[str | None] = mapped_column(String(40))
    random_seed: Mapped[int] = mapped_column(Integer, nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    verdict: Mapped[str] = mapped_column(String(48), nullable=False)
    gate_passed: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                              server_default=text("false"))
    leakage_passed: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                                 server_default=text("true"))
    #: The whole result document: metrics, controls, folds, gate, quality.
    result: Mapped[dict] = mapped_column(JSONB, nullable=False,
                                         server_default=text("'{}'::jsonb"))


class V6LabTrade(Base):
    """One simulated position. Censored rows are kept, and flagged."""

    __tablename__ = "v6lab_trades"
    __table_args__ = (
        Index("ix_v6lab_trades_run_strategy", "run_id", "strategy"),
        Index("ix_v6lab_trades_entry", "entry_ts"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    strategy: Mapped[str] = mapped_column(String(48), nullable=False)
    mint: Mapped[str] = mapped_column(String(64), nullable=False)

    entry_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_reason: Mapped[str] = mapped_column(String(24), nullable=False)
    #: True when the observation window closed before the rule resolved the
    #: trade. These rows have a NULL return and are never counted as zero.
    censored: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                           server_default=text("false"))

    entry_progress_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    entry_mcap_sol: Mapped[Decimal | None] = mapped_column(Numeric(30, 9))
    elapsed_s: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))

    gross_return: Mapped[Decimal | None] = mapped_column(_RET)
    net_return: Mapped[Decimal | None] = mapped_column(_RET)
    net_pnl_usd: Mapped[Decimal | None] = mapped_column(_USD)
    fees_usd: Mapped[Decimal | None] = mapped_column(_USD)
    slippage_usd: Mapped[Decimal | None] = mapped_column(_USD)
    mfe: Mapped[Decimal | None] = mapped_column(_RET)
    mae: Mapped[Decimal | None] = mapped_column(_RET)
    reached_100: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                              server_default=text("false"))
    graduated: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                            server_default=text("false"))
