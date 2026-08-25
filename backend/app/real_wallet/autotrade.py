"""The operator's start/stop control for autonomous trading.

Two asymmetric guarantees, and the asymmetry is the design:

* **Stopping is unconditional and immediate.** It needs no other condition to be
  true, it cannot fail on a barrier, and it takes effect on the next guard
  evaluation. A control an operator cannot trust to stop is a control they will
  be afraid to start.
* **Starting authorises nothing.** It records an intent. Mode, the three enable
  flags, the release constant, the mainnet clause, the submission guard, SEC-2
  freshness, network verification and the canary limits are each evaluated
  independently and are untouched by it. Starting on today's deployment leaves
  submission exactly as impossible as it was.

`nominated_strategy` records which V6 Lab strategy the operator intends to trade.
Recording is not promoting: nothing reads it as permission, and the evidence gate
in the funding report does not move because a name was typed into it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.real_wallet_execution import (
    RealWalletAutotradeEvent,
    RealWalletAutotradeSwitch,
)

logger = get_logger(__name__)

SCOPE = "default"


class UnknownStrategyError(ValueError):
    """A nomination must name a strategy that exists, or it names nothing."""


@dataclass(frozen=True, slots=True)
class AutotradeState:
    enabled: bool
    nominated_strategy: str | None
    started_at: datetime | None
    started_by: str | None
    start_reason: str | None
    stopped_at: datetime | None
    stopped_by: str | None
    stop_reason: str | None

    def as_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "nominated_strategy": self.nominated_strategy,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "started_by": self.started_by,
            "start_reason": self.start_reason,
            "stopped_at": self.stopped_at.isoformat() if self.stopped_at else None,
            "stopped_by": self.stopped_by,
            "stop_reason": self.stop_reason,
            # Restated on every read so a caller cannot infer permission from
            # `enabled` alone. This is the whole contract of the control.
            "authorises_execution": False,
        }


def _known_strategy(strategy_id: str) -> bool:
    from app.lab.spec import BY_ID

    return strategy_id.upper() in BY_ID


class AutotradeSwitchService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _row(self) -> RealWalletAutotradeSwitch:
        row = (
            await self._session.execute(
                select(RealWalletAutotradeSwitch).where(
                    RealWalletAutotradeSwitch.scope == SCOPE
                )
            )
        ).scalars().first()
        if row is None:
            row = RealWalletAutotradeSwitch(scope=SCOPE, enabled=False)
            self._session.add(row)
            await self._session.flush()
        return row

    async def state(self) -> AutotradeState:
        row = await self._row()
        return AutotradeState(
            enabled=row.enabled, nominated_strategy=row.nominated_strategy,
            started_at=row.started_at, started_by=row.started_by,
            start_reason=row.start_reason, stopped_at=row.stopped_at,
            stopped_by=row.stopped_by, stop_reason=row.stop_reason,
        )

    async def start(
        self, *, actor: str, reason: str, strategy_id: str, at: datetime
    ) -> AutotradeState:
        """Record the intent to trade. This grants no permission whatsoever."""
        if not _known_strategy(strategy_id):
            raise UnknownStrategyError(strategy_id)
        row = await self._row()
        row.enabled = True
        row.nominated_strategy = strategy_id.upper()
        row.started_at = at
        row.started_by = actor
        row.start_reason = reason
        self._session.add(RealWalletAutotradeEvent(
            scope=SCOPE, action="started", actor=actor, reason=reason,
            nominated_strategy=row.nominated_strategy, occurred_at=at,
        ))
        await self._session.flush()
        logger.info("real_wallet_autotrade_started", actor=actor,
                    strategy=row.nominated_strategy)
        return await self.state()

    async def stop(self, *, actor: str, reason: str, at: datetime) -> AutotradeState:
        """Stop autonomous trading. Unconditional — it can never be refused."""
        row = await self._row()
        row.enabled = False
        row.stopped_at = at
        row.stopped_by = actor
        row.stop_reason = reason
        self._session.add(RealWalletAutotradeEvent(
            scope=SCOPE, action="stopped", actor=actor, reason=reason,
            nominated_strategy=row.nominated_strategy, occurred_at=at,
        ))
        await self._session.flush()
        logger.warning("real_wallet_autotrade_stopped", actor=actor, reason=reason)
        return await self.state()

    async def history(self, *, limit: int = 50) -> list[RealWalletAutotradeEvent]:
        return list((await self._session.execute(
            select(RealWalletAutotradeEvent)
            .where(RealWalletAutotradeEvent.scope == SCOPE)
            .order_by(RealWalletAutotradeEvent.occurred_at.desc())
            .limit(limit)
        )).scalars())
