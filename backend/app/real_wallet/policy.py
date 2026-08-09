"""Independent hard limits for autonomous execution decisions."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.core.config import settings


class EntryMode(StrEnum):
    ENTRIES_AND_EXITS = "entries_and_exits"
    NO_NEW_ENTRIES_BUT_ALLOW_EXITS = "no_new_entries_but_allow_exits"


class PolicyReason(StrEnum):
    MODE_DISABLED = "MODE_DISABLED"
    MAX_OPEN_POSITIONS = "MAX_OPEN_POSITIONS"
    MAX_TOTAL_EXPOSURE = "MAX_TOTAL_EXPOSURE"
    MAX_DAILY_NOTIONAL = "MAX_DAILY_NOTIONAL"
    MAX_DAILY_LOSS = "MAX_DAILY_LOSS"


@dataclass(frozen=True, slots=True)
class PolicyState:
    open_positions: int
    exposure_usd: Decimal
    daily_notional_usd: Decimal
    daily_realised_loss_usd: Decimal


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason_codes: tuple[str, ...]


class AutonomousExecutionPolicy:
    """Server-owned limits. Strategy and frontend cannot override this policy."""

    def evaluate_entry(self, *, requested_usd: Decimal, state: PolicyState) -> PolicyDecision:
        reasons: list[str] = []
        if settings.REAL_WALLET_EXECUTION_MODE != "dry_run":
            reasons.append(PolicyReason.MODE_DISABLED)
        if state.open_positions >= settings.REAL_WALLET_MAX_OPEN_POSITIONS:
            reasons.append(PolicyReason.MAX_OPEN_POSITIONS)
        if state.exposure_usd + requested_usd > settings.REAL_WALLET_MAX_TOTAL_EXPOSURE_USD:
            reasons.append(PolicyReason.MAX_TOTAL_EXPOSURE)
        if (
            state.daily_notional_usd + requested_usd
            > settings.REAL_WALLET_MAX_DAILY_NOTIONAL_USD
        ):
            reasons.append(PolicyReason.MAX_DAILY_NOTIONAL)
        if state.daily_realised_loss_usd >= settings.REAL_WALLET_MAX_DAILY_LOSS_USD:
            reasons.append(PolicyReason.MAX_DAILY_LOSS)
        return PolicyDecision(allowed=not reasons, reason_codes=tuple(reasons))
