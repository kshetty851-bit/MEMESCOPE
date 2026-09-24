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
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.real_wallet_execution import (
    RealWalletAutotradeEvent,
    RealWalletAutotradeSwitch,
)

logger = get_logger(__name__)

SCOPE = "default"


class UnknownStrategyError(ValueError):
    """A nomination must name a strategy that exists, or it names nothing."""


class InvalidTicketError(ValueError):
    """A trade size Start cannot accept."""


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
    #: The graduation trade size chosen at Start; None trades the configured one.
    ticket_usd: Decimal | None = None

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
            "ticket_usd": (None if self.ticket_usd is None
                           else format(self.ticket_usd.normalize(), "f")),
            # Restated on every read so a caller cannot infer permission from
            # `enabled` alone. This is the whole contract of the control.
            "authorises_execution": False,
        }


def ticket_choices(strategy_id: str | None = None) -> list[Decimal]:
    """The trade sizes Start offers: the board's own splits of a $100 ticket,
    from the configured size down to `live_spec.MIN_TICKET_USD`.

    An arm may cap it lower: `live_spec.MAX_TICKET_USD`, whose comment says
    why G-BAS-5M is capped where it is."""
    from app.labs.graduation import config as grad
    from app.labs.graduation import live_spec

    ceiling = settings.REAL_WALLET_ENTRY_SIZE_USD
    if strategy_id:
        cap = live_spec.max_ticket(strategy_id)
        if cap is not None:
            ceiling = min(ceiling, cap)
    sizes = {grad.PAPER_NOTIONAL_USD / n for n in grad.WALLET_SPLITS}
    sizes |= set(live_spec.EXTRA_TICKETS_USD)
    return sorted((t for t in sizes if live_spec.MIN_TICKET_USD <= t <= ceiling),
                  reverse=True)


def ticket_for(state: AutotradeState, configured: Decimal) -> Decimal:
    """What a trade spends: the size chosen at Start, never above `configured`,
    and never above the nominated arm's own cap.

    The cap belongs here rather than at Start alone: `ticket_usd` may be None,
    which means "trade the configured size", and for a capped arm that would be
    $100 — the very size its evidence rules out. Every caller that spends money
    reads this function, so one guard covers them all.
    """
    from app.labs.graduation import live_spec

    size = configured if state.ticket_usd is None else min(configured, state.ticket_usd)
    cap = live_spec.max_ticket(state.nominated_strategy or "")
    return size if cap is None else min(size, cap)


def _known_strategy(strategy_id: str) -> bool:
    from app.lab.spec import BY_ID
    from app.labs.graduation.live_spec import BY_ID as GRAD_BY_ID

    # Two registries, because the graduation arm cannot live in the first one:
    # `SPEC_HASH` is taken over the whole of `app.lab.spec.STRATEGIES` and is
    # compared on every Lab tick, so adding an entry there drifts the hash and
    # halts V7. The arm carries its own spec_version and hash instead, exactly
    # as `pumpfun`, `compound` and `momentum` already do.
    return strategy_id.upper() in BY_ID or strategy_id.upper() in GRAD_BY_ID


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
            ticket_usd=row.ticket_usd,
        )

    async def start(
        self, *, actor: str, reason: str, strategy_id: str, at: datetime,
        ticket_usd: Decimal | None = None,
    ) -> AutotradeState:
        """Record the intent to trade. This grants no permission whatsoever.

        `ticket_usd` is the graduation trade size, one of the choices for THAT
        arm: the baseline is capped below B3, and accepting a larger size here
        would let a request set a size the page will not show. None trades the
        configured `REAL_WALLET_ENTRY_SIZE_USD`, as before.
        """
        from app.labs.graduation.live_spec import BY_ID as GRAD_BY_ID
        from app.labs.graduation.live_spec import OFFERED

        if not _known_strategy(strategy_id):
            raise UnknownStrategyError(strategy_id)
        # A graduation arm must be one the wallet still offers. Refused here,
        # not only hidden on the page, so a request cannot start an arm the
        # owner has retired.
        if strategy_id.upper() in GRAD_BY_ID and strategy_id.upper() not in OFFERED:
            raise UnknownStrategyError(f"{strategy_id.upper()} is no longer offered")
        if ticket_usd is not None:
            if strategy_id.upper() not in GRAD_BY_ID:
                raise InvalidTicketError("a trade size is chosen for graduation arms only")
            allowed = ticket_choices(strategy_id)
            if ticket_usd not in allowed:
                raise InvalidTicketError(
                    f"trade size for {strategy_id.upper()} must be one of "
                    f"{', '.join(format(t, 'f') for t in allowed)}")
        row = await self._row()
        row.enabled = True
        row.nominated_strategy = strategy_id.upper()
        row.ticket_usd = ticket_usd
        row.started_at = at
        row.started_by = actor
        row.start_reason = reason
        self._session.add(RealWalletAutotradeEvent(
            scope=SCOPE, action="started", actor=actor, reason=reason,
            nominated_strategy=row.nominated_strategy, ticket_usd=ticket_usd,
            occurred_at=at,
        ))
        await self._session.flush()
        logger.info("real_wallet_autotrade_started", actor=actor,
                    strategy=row.nominated_strategy,
                    ticket_usd=None if ticket_usd is None else str(ticket_usd))
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
