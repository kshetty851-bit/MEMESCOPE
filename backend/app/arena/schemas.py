"""Arena response models. Money as strings, absence as null — never zero."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from app.schemas.common import BaseSchema


class ArenaCandidateOut(BaseSchema):
    code: str
    name: str
    version: str
    status: str
    failed_reason: str | None = None
    starting_equity: Decimal
    #: Uninvested cash.
    cash: Decimal
    #: What the open positions COST — the capital they tie up. Not their worth.
    deployed_cost: Decimal
    #: What the open positions could actually be SOLD for right now, under the
    #: same execution model settlement uses. A position that has collapsed is
    #: worth what it would fetch, not what it cost.
    unrealized_value: Decimal
    #: unrealized_value - deployed_cost. Negative while open positions are down.
    unrealized_pnl: Decimal
    #: cash + unrealized_value. THE headline number.
    equity: Decimal
    #: cash + deployed_cost — what equity would read if open positions were
    #: carried at cost. Published beside the real figure so the difference
    #: between "capital committed" and "capital worth" is visible rather than
    #: implied.
    equity_at_cost: Decimal
    realized_pnl: Decimal
    total_return: Decimal
    trades: int
    wins: int
    losses: int
    #: None until a trade closes — an unmeasured rate is not a zero rate.
    win_rate: Decimal | None = None
    win_rate_ci_low: Decimal | None = None
    win_rate_ci_high: Decimal | None = None
    expectancy: Decimal | None = None
    profit_factor: Decimal | None = None
    avg_win: Decimal | None = None
    avg_loss: Decimal | None = None
    max_drawdown: Decimal
    open_positions: int
    skipped: int
    buy_failures: int
    sell_failures: int
    route_unknown: int
    reached_125: int
    reached_150: int
    reached_200: int


class ArenaDecisionOut(BaseSchema):
    code: str
    mint_address: str
    checkpoint_at: datetime
    eligible: bool
    skip_reason: str | None
    route_state: str | None
    features: dict[str, Any] | None


class ArenaBoard(BaseSchema):
    candidates: list[ArenaCandidateOut]
    checkpoint_minutes: int
    rules_version: str
    valid_from: datetime | None
    disclosure: str
    observed_at: datetime
