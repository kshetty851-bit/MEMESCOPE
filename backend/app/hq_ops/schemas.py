"""Response models for `GET /api/v1/hq/operations`.

Every component reports a `status` and, separately, whether it was actually
measured. Those are not the same question and collapsing them is the failure
this whole surface exists to avoid: a component the API cannot see must not
come back `healthy`, and it must not come back `down` either — it comes back
`unknown`, with a sentence saying why nobody knows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import BaseSchema

#: Four states, not three. `unknown` is the one that keeps this honest.
ComponentStatus = Literal["healthy", "degraded", "down", "unknown"]


class ComponentHealth(BaseSchema):
    """One piece of infrastructure, and the evidence behind the verdict."""

    #: Stable identifier the frontend keys off. Never rendered raw.
    component: str
    status: ComponentStatus
    #: What was measured, in a sentence a person can read. Never a verdict on
    #: something that was not measured.
    detail: str
    #: Round-trip of the probe itself, where a round trip is what was measured.
    #: `None` when the component is not probed by latency.
    latency_ms: float | None = None
    #: False when the probe could not run at all. A reader has to be able to
    #: tell "we looked and it is fine" from "we could not look".
    measured: bool = True


class DiskHealth(BaseSchema):
    """Disk, which is the failure that took the platform down once already.

    On 2026-08-20 the volume reached 100%: Redis could not write its RDB,
    returned MISCONF on every write, and the pipeline stopped. The thresholds
    here are the same ones the retention task acts on, read from settings
    rather than restated, so HQ and the remediation cannot disagree about what
    "critical" means.
    """

    status: ComponentStatus
    percent_used: float | None
    warning_percent: float
    critical_percent: float
    measured: bool = True
    detail: str


class WorkerHealth(BaseSchema):
    """The Celery consumer loop, asked the only question that distinguishes a
    working worker from a wedged one: does it answer a ping.

    A wedged worker keeps its TCP connections, keeps its container `running`,
    and consumes nothing. Counting processes would call that healthy. Only the
    control channel knows the difference.
    """

    status: ComponentStatus
    #: Node names that replied, e.g. `celery@a106d6f2e262`. Empty when none did.
    nodes: list[str]
    replies: int
    measured: bool = True
    detail: str


class SchedulerHealth(BaseSchema):
    """Beat, judged by a heartbeat it writes rather than by a process listing.

    Beat has no control channel — it only sends — and it runs in a container
    the API cannot see into. So it publishes a timestamp on its own schedule
    and this reports how long ago that was. A scheduler that has stopped
    scheduling stops writing, which is exactly the signal wanted.
    """

    status: ComponentStatus
    last_beat: datetime | None
    seconds_since_beat: float | None
    #: The window a beat must arrive within before this degrades.
    expected_within_seconds: float
    measured: bool = True
    detail: str


class QueueHealth(BaseSchema):
    """Depth of the broker queues, which is work waiting for a worker."""

    status: ComponentStatus
    #: Queue name → pending messages. Empty when the broker was unreachable.
    depths: dict[str, int]
    total: int | None
    measured: bool = True
    detail: str


class OperationsHealth(BaseSchema):
    """Everything HQ's production watch can actually see.

    `containers` is deliberately absent. The API runs inside one container and
    has no Docker socket — by design, since a web process that can restart its
    own siblings is a web process worth attacking. Docker state is therefore
    not something this endpoint can report, and inventing it would be exactly
    the fabrication the HQ brief forbids.
    """

    disk: DiskHealth
    redis: ComponentHealth
    database: ComponentHealth
    worker: WorkerHealth
    scheduler: SchedulerHealth
    queues: QueueHealth
    #: Worst status across everything that was actually measured. Components
    #: that could not be probed do not drag this down — they are reported as
    #: `unknown` on their own row, where a reader can see them.
    overall: ComponentStatus
    #: How many components could not be measured at all.
    unmeasured: int
    environment: str
    version: str
    observed_at: datetime


class IncidentAction(BaseSchema):
    """One row of the autonomous audit trail."""

    at: datetime
    agent: str
    action: str
    autonomy: str
    reason: str
    outcome: str
    preconditions: dict[str, object]
    result: dict[str, object]
    verification: dict[str, object]


class Incident(BaseSchema):
    """An incident, an investigation, or a request awaiting the owner."""

    code: str
    kind: str
    component: str
    severity: str
    status: str
    autonomy: str
    agent: str | None
    signature: str
    symptoms: dict[str, object]
    root_cause: str | None
    owner_rationale: str | None
    detected_at: datetime
    resolved_at: datetime | None
    actions: list[IncidentAction] = Field(default_factory=list)


class RemediationInfo(BaseSchema):
    """One entry of the allowlist, published so the UI cannot invent others."""

    key: str
    autonomy: str
    agent: str
    summary: str
    reversible: bool


class HqOperations(BaseSchema):
    """Everything HQ's operational layer knows, in one response.

    One endpoint rather than five, because the alternative is a frontend that
    opens five polling loops and then has to decide what to show when three of
    them succeeded. A single reading is a single truth.
    """

    health: OperationsHealth
    #: Open work, newest first.
    incidents: list[Incident]
    #: Recently closed, so the room can show what just happened.
    recent: list[Incident]
    #: The audit trail across all incidents, newest first.
    activity: list[IncidentAction]
    #: Exactly what HQ is permitted to do. Published so a reader can check the
    #: claim rather than take it on faith.
    allowlist: list[RemediationInfo]
    #: The protected trading rules, as currently read.
    invariants: dict[str, object]
