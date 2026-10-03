"""The rug brake: one more rug while the main wallet is under $150 stops the
trading, across every wallet (Karthik, 2026-10-03: "if we have 1 more rug
before 150$ main balance, stop the trading accros all wallets").

It presses the same STOP as the page — `AutotradeSwitchService.stop` — and
the user wallets only buy while the main one is on, so all buying stops.
Selling is untouched: an open coin still leaves at its own time.

A rug is a closed trade in ANY wallet that got back under half the SOL it
put in. It counts only if it closed after the brake was set AND after the
last Start, so Karthik starting again by hand is never stopped by the rug
he restarted after. The worth is read when a new rug is first seen; an
unreadable worth is asked again next pass rather than guessed.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.real_wallet_execution import RealWalletPosition
from app.real_wallet.autotrade import AutotradeSwitchService

logger = get_logger(__name__)

#: When Karthik asked for it (11:46 Dubai): the morning's two rugs came before.
ARMED_AT = datetime(2026, 10, 3, 7, 46, tzinfo=UTC)
#: The main wallet's worth under which one more rug stops everything.
BELOW_USD = Decimal(150)
ACTOR = "rug_brake"

#: Rugs already weighed in this process, so a rug that came while the wallet
#: was worth $150+ is not weighed again on every pass.
_weighed: set[uuid.UUID] = set()


async def pull_if_due(session: AsyncSession, now: datetime,
                      worth: Callable[[], Awaitable[Decimal | None]]) -> bool:
    """Stop the trading if a new rug came while the main wallet is under
    `BELOW_USD`. True when it stopped it."""
    switch = AutotradeSwitchService(session)
    state = await switch.state()
    if not state.enabled:
        return False
    since = max(ARMED_AT, state.started_at or ARMED_AT)
    rugs = [r for r in (await session.scalars(
        select(RealWalletPosition.id).where(
            RealWalletPosition.status == "CLOSED",
            RealWalletPosition.closed_at >= since,
            RealWalletPosition.exit_actual_output_amount
            < RealWalletPosition.entry_actual_input_amount / 2))).all()
        if r not in _weighed]
    if not rugs:
        return False
    value = await worth()
    if value is None:
        return False            # asked again next pass
    _weighed.update(rugs)
    if value >= BELOW_USD:
        logger.warning("real_wallet_rug_brake_held", worth=str(value), rugs=len(rugs))
        return False
    await switch.stop(
        actor=ACTOR, at=now,
        reason=f"rug while the main wallet was worth ${value:.2f}, under ${BELOW_USD}")
    return True
