"""Paper wallet database access.

The package's only I/O seam besides `service.py`, `scheduler.py` and `api.py`.
Everything above this line is pure.

Two guarantees are enforced here rather than in application logic:

* **A token is entered once, ever.** `open_position` inserts with
  `ON CONFLICT DO NOTHING` against `uq_paper_positions_wallet_mint` and returns
  `None` when the row already exists. Two evaluators racing the same Radar page
  cannot double-buy, and a re-run of the same pass is a no-op.
* **The entry block is never rewritten.** The update statements below touch only
  the evaluator's columns; nothing in this file can move an entry price, a
  target or a stop after the fact.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.paper import PaperPosition, PaperWallet
from app.paper.models import PositionStatus


class PaperRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- Wallet --------------------------------------------------------------

    async def wallet_for(self, strategy_id: str) -> PaperWallet | None:
        found: PaperWallet | None = await self._session.scalar(
            select(PaperWallet).where(PaperWallet.strategy_id == strategy_id)
        )
        return found

    async def ensure_wallet(
        self, *, strategy_id: str, strategy_version: str, starting_balance: Decimal
    ) -> PaperWallet:
        """Get the wallet for a strategy, creating it once.

        Concurrency-safe rather than check-then-insert: two workers starting
        together would otherwise both see no wallet and both insert one, and the
        unique constraint would fail the second mid-transaction. `ON CONFLICT DO
        NOTHING` followed by a read resolves either way to the same single row.

        `starting_balance` is only ever applied at creation. Changing the
        setting later must not restate returns that were already published, so
        an existing wallet keeps the balance it started with.
        """
        await self._session.execute(
            insert(PaperWallet)
            .values(
                strategy_id=strategy_id,
                strategy_version=strategy_version,
                starting_balance=starting_balance,
            )
            .on_conflict_do_nothing(index_elements=[PaperWallet.strategy_id])
        )
        await self._session.flush()
        wallet = await self.wallet_for(strategy_id)
        if wallet is None:  # pragma: no cover - the insert above guarantees it
            raise RuntimeError(f"paper wallet for {strategy_id!r} could not be created")
        return wallet

    # --- Positions -----------------------------------------------------------

    def _for_wallet(self, wallet_id: uuid.UUID) -> Select[tuple[PaperPosition]]:
        return select(PaperPosition).where(PaperPosition.wallet_id == wallet_id)

    async def open_position(self, **values: Any) -> PaperPosition | None:
        """Insert one position, or return `None` if the token was already taken.

        `None` is the ordinary path, not an error: the evaluator offers every
        Top-10 token on every pass, and all but the newest are already held or
        already closed. The database is what decides, which is what makes "the
        first time it enters the Top 10" true rather than merely intended.
        """
        result = await self._session.execute(
            insert(PaperPosition)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[PaperPosition.wallet_id, PaperPosition.mint_address]
            )
            .returning(PaperPosition)
        )
        return result.scalar_one_or_none()

    async def open_positions(
        self, wallet_id: uuid.UUID, *, limit: int | None = None
    ) -> Sequence[PaperPosition]:
        """Running positions, oldest watermark first.

        The order is the anti-starvation rule: a bounded batch taken in
        arbitrary heap order returns the same rows every cycle and the tail
        never advances. That is the failure that livelocked the score sweep, and
        the tiebreak on mint keeps it deterministic when watermarks match.
        """
        statement = (
            self._for_wallet(wallet_id)
            .where(PaperPosition.status == PositionStatus.OPEN.value)
            .order_by(PaperPosition.last_evaluated_at.asc(), PaperPosition.mint_address.asc())
        )
        if limit is not None:
            statement = statement.limit(limit)
        return (await self._session.scalars(statement)).all()

    async def closed_positions(self, wallet_id: uuid.UUID) -> Sequence[PaperPosition]:
        """Every finished trade, newest first. Losers included, always."""
        return (
            await self._session.scalars(
                self._for_wallet(wallet_id)
                .where(PaperPosition.status == PositionStatus.CLOSED.value)
                .order_by(PaperPosition.closed_at.desc(), PaperPosition.mint_address.asc())
            )
        ).all()

    async def all_positions(self, wallet_id: uuid.UUID) -> Sequence[PaperPosition]:
        """Open and closed together, for surfaces that index by mint.

        One query rather than two: the Track Record asks "was this token
        traded?" of a hundred mints at once, and the answer is the same row set
        the positions page already reads.
        """
        return (
            await self._session.scalars(
                self._for_wallet(wallet_id).order_by(
                    PaperPosition.opened_at.desc(), PaperPosition.mint_address.asc()
                )
            )
        ).all()

    async def position_for(
        self, wallet_id: uuid.UUID, mint_address: str
    ) -> PaperPosition | None:
        found: PaperPosition | None = await self._session.scalar(
            self._for_wallet(wallet_id).where(PaperPosition.mint_address == mint_address)
        )
        return found

    async def held_mints(self, wallet_id: uuid.UUID) -> set[str]:
        """Every mint this wallet has ever taken, open or closed.

        Read before entry so the evaluator skips tokens it cannot buy without
        issuing an insert per candidate. The unique index is still the
        guarantee; this only keeps the common case off the write path.
        """
        rows = await self._session.scalars(
            select(PaperPosition.mint_address).where(PaperPosition.wallet_id == wallet_id)
        )
        return set(rows.all())

    # --- The evaluator's writes ---------------------------------------------

    async def advance(
        self,
        position_id: uuid.UUID,
        *,
        peak_price: Decimal,
        last_evaluated_at: datetime,
    ) -> None:
        """Move a still-open position's watermark and running peak.

        Touches nothing else. The entry block is immutable by construction: no
        statement in this file names those columns in an UPDATE.
        """
        await self._session.execute(
            update(PaperPosition)
            .where(PaperPosition.id == position_id)
            .values(peak_price=peak_price, last_evaluated_at=last_evaluated_at)
        )

    async def close(
        self,
        position_id: uuid.UUID,
        *,
        exit_price: Decimal,
        closed_at: datetime,
        exit_reason: str,
        peak_price: Decimal,
    ) -> None:
        """Record a close, once.

        Guarded on `status = 'open'` rather than on the id alone, so a duplicate
        pass over the same position cannot rewrite an exit that already
        happened. A closed trade is part of the permanent record.
        """
        await self._session.execute(
            update(PaperPosition)
            .where(
                PaperPosition.id == position_id,
                PaperPosition.status == PositionStatus.OPEN.value,
            )
            .values(
                status=PositionStatus.CLOSED.value,
                exit_price=exit_price,
                closed_at=closed_at,
                exit_reason=exit_reason,
                peak_price=peak_price,
                last_evaluated_at=closed_at,
            )
        )
