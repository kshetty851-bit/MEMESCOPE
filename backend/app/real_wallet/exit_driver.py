"""Close real positions by the rules they were opened under.

The real wallet could open a position and never close one. `driver.py` creates
BUY intents; everything downstream of a SELL was built — the order factory, the
evidence re-check, reconciliation, P&L — and nothing in production ever decided
to sell. The only caller of `create_sell_intent` was the test-only lifecycle,
which refuses outside `ENVIRONMENT=test`. A wallet that buys and never sells
realises no profit and compounds nothing.

## It owns no exit rule

`evaluate_exit` is the Lab's, and it is imported rather than reimplemented. Two
implementations of "when do we sell" would eventually disagree, and the first
time they did, the paper record and the real record would stop describing the
same strategy. The Lab is the one place exit logic lives; this asks it.

## Positions exit by the rules they ENTERED under

The strategy comes from the POSITION, never from the currently nominated one. An
operator who switches strategy mid-flight has changed what gets bought next, not
what the open book promised — a position opened under a 1.25x take-profit must
still exit at 1.25x even if the switch now names something else. Reading the
nominated strategy here would silently re-write the exit rules of every open
position the moment the operator changed their mind.

## What it cannot do

It creates intents. It does not assemble orders, sign, or submit — each of those
has its own barrier, and the transport still refuses on mainnet. Creating a SELL
intent is not selling.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.lab import execution, spec
from app.lab.rules import MarkState, evaluate_exit
from app.models.real_wallet_execution import RealWalletPosition
from app.real_wallet.live_repository import (
    LiveIntentRepository,
    PositionExitAlreadyRequestedError,
)
from app.repositories.market import MarketSnapshotRepository

logger = get_logger(__name__)

#: The stagnation band, matching the Lab's. A multiple inside it is "flat".
FLAT_BAND = (Decimal("0.95"), Decimal("1.05"))


@dataclass(frozen=True, slots=True)
class ExitOutcome:
    marked: int
    exits_requested: int
    skipped: dict[str, int]

    def as_dict(self) -> dict[str, object]:
        return {"marked": self.marked, "exits_requested": self.exits_requested,
                "skipped": self.skipped}


class RealWalletExitDriver:
    """Mark every open real position and request the exit its rules call for."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = LiveIntentRepository(session)
        self._markets = MarketSnapshotRepository(session)

    async def tick(self, *, now: datetime | None = None) -> ExitOutcome:
        now = now or datetime.now(UTC)
        positions = list((await self._session.scalars(
            select(RealWalletPosition)
            .where(RealWalletPosition.status == "OPEN")
            .order_by(RealWalletPosition.opened_at)
        )).all())

        marked = requested = 0
        skipped: dict[str, int] = {}

        def skip(reason: str) -> None:
            skipped[reason] = skipped.get(reason, 0) + 1

        for pos in positions:
            if pos.exit_intent_id is not None:
                skip("exit_already_requested")
                continue
            strategy = spec.BY_ID.get((pos.strategy_id or "").upper())
            if strategy is None:
                # An exit rule we cannot read is not an exit rule we may guess.
                skip("unknown_strategy")
                continue

            state = await self._mark(pos, strategy, now)
            if state is None:
                skip("unpriceable")
                continue
            marked += 1

            verdict = evaluate_exit(strategy.exits, state)
            if verdict.action is None:
                continue
            # `create_sell_intent` binds the FULL confirmed quantity, so a
            # partial cannot be expressed yet. Promoting it to a close banks the
            # profit early rather than letting the position run past a level its
            # rules said to sell at, and the reason records that it happened.
            # ponytail: real partials need a fractional-quantity SELL intent.
            reason = (f"partial_promoted_to_close:{verdict.reason}"
                      if verdict.action == "PARTIAL" else verdict.reason)
            try:
                await self._request_exit(pos, strategy, reason=reason, now=now)
            except PositionExitAlreadyRequestedError:
                skip("exit_already_requested")
                continue
            requested += 1

        return ExitOutcome(marked=marked, exits_requested=requested, skipped=skipped)

    # --- marking ------------------------------------------------------------

    async def _mark(
        self, pos: RealWalletPosition, strategy: spec.Strategy, now: datetime
    ) -> MarkState | None:
        """Update the position's live state and return what the rules read.

        An unpriceable position is NOT marked and NOT exited. A stale or missing
        price is an absence of information, and selling on one would be acting on
        a number nobody currently observes — the Lab treats staleness the same
        way, and the two records have to agree.
        """
        snapshot = await self._markets.latest_for_mint(pos.mint_address)
        if snapshot is None or snapshot.price_usd is None:
            return None
        captured = snapshot.captured_at
        if captured is not None and execution.is_stale(captured, now):
            return None

        price = Decimal(str(snapshot.price_usd))
        liquidity = (Decimal(str(snapshot.liquidity_usd))
                     if snapshot.liquidity_usd is not None else None)
        entry_price = Decimal(str(pos.entry_price_usd or 0))
        quantity = Decimal(str(pos.quantity or 0))
        if entry_price <= 0 or quantity <= 0:
            return None

        cost = entry_price * quantity
        proceeds = execution.sell_proceeds(quantity, price, liquidity or Decimal(0))
        exec_multiple = (proceeds / cost) if cost > 0 else Decimal(0)

        # Peak only ever rises. A trailing stop measured against a peak that can
        # fall is not a trailing stop.
        if exec_multiple > Decimal(str(pos.peak_exec_multiple or 1)):
            pos.peak_exec_multiple = exec_multiple
        pos.last_exec_multiple = exec_multiple
        pos.last_marked_at = now

        arm = strategy.exits.break_even_arm
        if arm is not None and not pos.break_even_armed and exec_multiple >= arm:
            pos.break_even_armed = True

        low, high = FLAT_BAND
        if low <= exec_multiple <= high:
            if pos.flat_since is None:
                pos.flat_since = now
        else:
            pos.flat_since = None

        held_hours = (now - _aware(pos.opened_at)).total_seconds() / 3600
        flat_hours = ((now - _aware(pos.flat_since)).total_seconds() / 3600
                      if pos.flat_since else 0.0)
        return MarkState(
            exec_multiple=exec_multiple,
            peak_exec_multiple=Decimal(str(pos.peak_exec_multiple or 1)),
            held_hours=held_hours,
            liquidity_usd=liquidity,
            entry_liquidity_usd=(Decimal(str(pos.entry_liquidity_usd))
                                 if pos.entry_liquidity_usd is not None else None),
            # Zero proceeds against a real cost is a dead pool, not a cheap one.
            is_dead=proceeds <= 0,
            # Unknown route is unknown, never "fine": the guard and the order
            # factory both re-check a real sell route before anything is signed.
            sell_route_ok=None,
            break_even_armed=bool(pos.break_even_armed),
            partial_done=bool(pos.partial_done),
            flat_hours=flat_hours,
        )

    async def _request_exit(
        self, pos: RealWalletPosition, strategy: spec.Strategy, *,
        reason: str, now: datetime,
    ) -> None:
        intent = await self._repository.create_sell_intent(
            # One exit per position, ever. The position id is the key because
            # the position is the thing being closed; a timestamp here would let
            # a retry open a second exit for the same holding.
            idempotency_key=f"v6exit:{pos.id}",
            position_id=pos.id,
            strategy_id=strategy.id,
            strategy_version=settings.REAL_WALLET_SAFETY_POLICY_VERSION,
            wallet_public_key=pos.wallet_public_key,
            output_mint=settings.JUPITER_USDC_MINT,
        )
        pos.exit_reason = reason[:64]
        logger.warning("real_wallet_exit_requested", position_id=str(pos.id),
                       mint=pos.mint_address, strategy=strategy.id,
                       reason=reason, intent_id=str(intent.id))


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


__all__ = ["ExitOutcome", "RealWalletExitDriver"]
