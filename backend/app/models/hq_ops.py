"""HQ's operational record: incidents, and every autonomous action taken.

These tables exist so that operational truth survives a page refresh, and so
that "Patch repaired the worker at 02:15" is a row somebody can audit rather
than an animation somebody wrote.

── WHY THESE ARE THEIR OWN TABLES ───────────────────────────────────────

The HQ brief is explicit that no trading table may be reshaped for HQ's
convenience, and the reasoning holds independently: an observability feature
that shares a table with the paper wallet is an observability feature that can
corrupt the paper wallet. Nothing here has a foreign key into a trading table,
and nothing in trading reads from these. The coupling is one-way and it is
through the read-only probe, not the schema.

── WHY THE AUDIT ROWS ARE APPEND-ONLY ───────────────────────────────────

`hq_actions` is written once per attempted action and never updated. An audit
trail you can edit is a story, not a record — and the specific thing it has to
survive is the case where a repair made things worse and somebody wants to
know exactly what ran, in what order, against what preconditions.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class HqIncident(Base):
    """One piece of operational work: an incident, an investigation or a
    request that only the owner may approve.

    Three kinds in one table rather than three tables, because they share every
    column that matters — who owns it, what component it concerns, what was
    observed, how it ended — and differ only in how they start. A separate
    table per kind would be three copies of the same lifecycle.
    """

    __tablename__ = "hq_incidents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    #: Human-facing reference, e.g. `INC-28`. Monotonic per kind, assigned on
    #: insert from `sequence`, so an operator can say a number out loud.
    code: Mapped[str] = mapped_column(String(24), nullable=False, unique=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    #: `incident` | `investigation` | `approval`.
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    #: Which component this concerns: `worker`, `disk`, `redis`, …
    component: Mapped[str] = mapped_column(String(64), nullable=False)
    #: `info` | `degraded` | `critical`.
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    #: `open` | `investigating` | `repairing` | `verifying` | `awaiting_owner`
    #: | `resolved` | `failed`.
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    #: `green` | `yellow` | `red`. Decides what may run without a human.
    autonomy: Mapped[str] = mapped_column(String(8), nullable=False)

    #: Which HQ agent currently holds it. An employee id, never a user.
    agent: Mapped[str | None] = mapped_column(String(32), nullable=True)

    #: Stable identity of the condition, so a flapping component reopens the
    #: same incident instead of creating one every tick. This plus an open
    #: status is the idempotency key the detector relies on.
    signature: Mapped[str] = mapped_column(String(128), nullable=False)

    #: What was actually observed at detection, verbatim from the probe.
    symptoms: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    #: Filled in only when something established it. Never a guess.
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Why this needs a person, for `approval` rows.
    owner_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        # The detector's hot path: "is there already an open incident for this
        # condition". Without this it is a sequential scan every single tick.
        Index("ix_hq_incidents_signature_status", "signature", "status"),
        Index("ix_hq_incidents_status_detected", "status", "detected_at"),
        Index("ix_hq_incidents_kind_detected", "kind", "detected_at"),
    )


class HqAction(Base):
    """One attempted autonomous action, written whatever the outcome.

    Written *before* the action runs and completed after, so an action that
    crashes the process still leaves a row saying it was attempted. A trail
    that only records successes cannot explain an outage.
    """

    __tablename__ = "hq_actions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hq_incidents.id", ondelete="CASCADE"),
        nullable=True,
    )

    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    #: Which agent is credited. Must match an HQ employee id — the room shows
    #: this, and a name here that nobody recognises is a name the room invents.
    agent: Mapped[str] = mapped_column(String(32), nullable=False)
    #: The allowlist key that ran, e.g. `worker.pool_restart`. Never free text
    #: from a request: the executor looks this up in a table compiled into the
    #: image, and anything absent from it cannot run.
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    autonomy: Mapped[str] = mapped_column(String(8), nullable=False)
    #: Why it ran, in a sentence.
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    #: `attempted` | `skipped` | `succeeded` | `failed` | `rolled_back`.
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Preconditions as they were evaluated, the raw result, and the
    #: verification reading afterwards. Everything needed to argue about it
    #: later without re-running anything.
    preconditions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    verification: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    __table_args__ = (
        Index("ix_hq_actions_at", "at"),
        Index("ix_hq_actions_incident", "incident_id", "at"),
    )
