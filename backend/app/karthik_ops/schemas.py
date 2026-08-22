"""Response models for `GET /api/v1/karthik`.

One endpoint, one response, for the reason `hq_ops` gives: five responses can
disagree, and a panel assembled from disagreeing readings is a panel nobody can
check. The Karthik Lab's six screens, his incident queue, his action log, his
integrity score and his reports all come from this one object.

Every screen carries `measured` separately from its values, and the values are
strings for money and `None` for absent. Strings because a JSON number would
round a price stored to eighteen places; `None` because a screen that renders
"we could not look" as `0` is the failure this whole surface exists to avoid.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import BaseSchema


class ScreenReading(BaseSchema):
    """One of the six monitors in Karthik Lab."""

    measured: bool
    #: What was read, or why nothing could be. Rendered verbatim on the screen.
    detail: str
    values: dict[str, object] = Field(default_factory=dict)
    rows: list[dict[str, object]] = Field(default_factory=list)


class WalletBinding(BaseSchema):
    """Which wallet Karthik operates, or a precise account of why none."""

    state: Literal["bound", "unbound", "forbidden", "designated_but_missing"]
    designated_strategy_id: str
    detail: str
    readable: bool
    needs_owner: bool
    wallet_id: str | None = None
    strategy_version: str | None = None
    generation: int | None = None
    starting_balance: str | None = None
    started_at: datetime | None = None
    archived_at: datetime | None = None


class IntegrityDeduction(BaseSchema):
    """One factor's contribution to the integrity score."""

    factor: str
    label: str
    penalty: int
    measured: bool
    detail: str


class ExperimentIntegrity(BaseSchema):
    """§11. `score` is `None` when nothing could be measured — never 0, never 100."""

    score: int | None
    band: Literal["HEALTHY", "DEGRADED", "UNRELIABLE", "NOT MEASURED"]
    headline: str
    deductions: list[IntegrityDeduction] = Field(default_factory=list)
    unmeasured: int = 0


class KarthikAction(BaseSchema):
    """One row of §10's action log. Append-only; failures included."""

    at: datetime
    agent: str
    action: str
    #: `green` | `yellow` | `red`. What class of action this is.
    autonomy: str
    #: `allowed` | `observe_only` | `not_allowlisted`. What happened to *this*
    #: attempt. Separate from `autonomy` because "allowlisted but not armed" and
    #: "not allowlisted at all" are the two facts a reviewer needs apart.
    verdict: str | None = None
    reason: str
    outcome: str
    preconditions: dict[str, object] = Field(default_factory=dict)
    result: dict[str, object] = Field(default_factory=dict)
    verification: dict[str, object] = Field(default_factory=dict)


class KarthikIncident(BaseSchema):
    """One finding: an incident, an owner request, or a recorded observation."""

    code: str
    kind: str
    component: str
    severity: str
    status: str
    autonomy: str
    agent: str | None
    signature: str
    symptoms: dict[str, object] = Field(default_factory=dict)
    root_cause: str | None = None
    owner_rationale: str | None = None
    detected_at: datetime
    resolved_at: datetime | None = None
    actions: list[KarthikAction] = Field(default_factory=list)


class SafeRepairInfo(BaseSchema):
    """One entry of §8's allowlist, published so the UI cannot invent others."""

    key: str
    summary: str
    precondition: str
    reversible: bool


class DefectCheck(BaseSchema):
    """One entry of §16's list, and whether Karthik can actually check it."""

    key: str
    label: str
    rectification: Literal["AUTO_FIX", "OWNER_REQUIRED", "OBSERVE_ONLY"]
    severity: str
    detectable: bool
    gap: str | None = None


class KarthikReport(BaseSchema):
    """§12. Every figure optional; an absent figure is absent, not zero."""

    window: str
    since: str | None
    until: str
    measured: bool
    detail: str
    starting_equity_usd: str | None = None
    ending_equity_usd: str | None = None
    pnl_usd: str | None = None
    opportunities: int | None = None
    entered: int | None = None
    targets_hit: int | None = None
    dead_zero: int | None = None
    open_positions: int | None = None
    closed_positions: int | None = None
    best_trade: dict[str, object] | None = None
    worst_trade: dict[str, object] | None = None
    average_hold_seconds: float | None = None
    target_hit_rate: float | None = None
    dead_rate: float | None = None
    cash_utilisation: float | None = None
    bugs_detected: int | None = None
    repairs_performed: int | None = None
    owner_attention: int | None = None
    integrity: dict[str, object] | None = None
    daily_series: list[dict[str, object]] = Field(default_factory=list)


class WhileAwaySummary(BaseSchema):
    """§13, answering "what happened while I was away" for one reader."""

    since: str | None
    until: str
    measured: bool
    detail: str
    opportunities: int | None = None
    new_trades: int | None = None
    targets_hit: int | None = None
    dead_positions: int | None = None
    pnl_usd: str | None = None
    biggest_winner: dict[str, object] | None = None
    biggest_loss: dict[str, object] | None = None
    bugs_found: int | None = None
    bugs_fixed: int | None = None
    owner_attention: int | None = None
    integrity_score: int | None = None


class KarthikScreens(BaseSchema):
    """The six monitors, named as §4 names them."""

    wallet: ScreenReading
    feed: ScreenReading
    positions: ScreenReading
    targets: ScreenReading
    health: ScreenReading
    reports: ScreenReading


class KarthikState(BaseSchema):
    """Everything Karthik knows, in one response.

    `autonomy` is published rather than inferred. A panel that guessed it would
    either claim repairs that cannot happen or hide ones that can, and §23
    makes the mode a fact the reader is entitled to see.
    """

    binding: WalletBinding
    autonomy: Literal["OBSERVE_ONLY", "SAFE_AUTOREPAIR"]
    screens: KarthikScreens
    accounting: ScreenReading
    integrity: ExperimentIntegrity
    #: Open work, newest first. Owner requests are the `karthik_approval` kind.
    incidents: list[KarthikIncident] = Field(default_factory=list)
    #: Closed in the last 24 hours.
    recent: list[KarthikIncident] = Field(default_factory=list)
    #: §10's log, newest first. Refusals included — especially refusals.
    actions: list[KarthikAction] = Field(default_factory=list)
    #: §8, published so a reader can check the claim rather than take it.
    allowlist: list[SafeRepairInfo] = Field(default_factory=list)
    #: §16, including the conditions no available evidence can establish.
    checks: list[DefectCheck] = Field(default_factory=list)
    reports: dict[str, KarthikReport] = Field(default_factory=dict)
    while_away: WhileAwaySummary
    observed_at: datetime
