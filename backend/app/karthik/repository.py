"""Every database access the Karthik wallet makes.

Two rules govern this file, and both are checkable by reading it:

* **It writes to three tables and no others** — `karthik_wallets`,
  `karthik_opportunities`, `karthik_positions`. It reads `radar_tokens`,
  `discovered_tokens` and `token_market_snapshots`, and it never writes to any
  of them. Karthik consumes the Track Record; it can never influence what the
  Track Record admits. `test_karthik_isolation.py` proves this by parsing the
  module rather than by trusting the sentence.
* **Nothing here touches a paper-wallet table.** Not the wallets, not the
  positions, not the audit. The Original Paper Wallet's cash is not reachable
  from this file, which is what makes "Karthik cannot spend the Original
  wallet's money" a property of the code rather than a promise.

Idempotency is the database's job, as everywhere else in this codebase: unique
indexes plus `ON CONFLICT DO NOTHING`, never check-then-insert.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.karthik import KarthikOpportunity, KarthikPosition, KarthikWallet
from app.models.radar import RadarToken


class KarthikRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- The wallet ----------------------------------------------------------

    async def wallet(self) -> KarthikWallet | None:
        """The one Karthik wallet, or `None` before activation.

        `None` is the ordinary pre-activation state and not an error. It is also
        the whole of Karthik's off switch: with no wallet row there is nothing
        to trade with, nothing to monitor, and the review task returns
        immediately.
        """
        found: KarthikWallet | None = await self._session.scalar(select(KarthikWallet))
        return found

    async def activate(
        self,
        *,
        name: str,
        starting_capital: Decimal,
        trade_size: Decimal,
        take_profit_multiple: Decimal,
        activated_at: datetime,
    ) -> KarthikWallet:
        """Create the wallet once, or return the one that already exists.

        `ON CONFLICT DO NOTHING` against the singleton index rather than
        check-then-insert: two operators (or an operator and a retry) running
        this together must not produce two wallets, and must not raise either.
        A second activation is a no-op that returns the first — which is why
        `activated_at` cannot be moved by re-running it.
        """
        existing = await self.wallet()
        if existing is not None:
            return existing

        await self._session.execute(
            insert(KarthikWallet)
            .values(
                name=name,
                starting_capital=starting_capital,
                trade_size=trade_size,
                take_profit_multiple=take_profit_multiple,
                activated_at=activated_at,
            )
            .on_conflict_do_nothing()
        )
        await self._session.flush()
        created = await self.wallet()
        assert created is not None  # the insert above either won or lost to one
        return created

    async def lock_wallet(self, wallet_id: uuid.UUID) -> None:
        """Serialize allocation so two passes cannot spend the same $10 twice."""
        await self._session.execute(
            select(KarthikWallet.id).where(KarthikWallet.id == wallet_id).with_for_update()
        )

    # --- Eligibility: reading the Track Record, never writing it -------------

    async def undecided_admissions(
        self, *, wallet: KarthikWallet, limit: int, as_of: datetime
    ) -> Sequence[RadarToken]:
        """Track Record admissions after activation that Karthik has not judged.

        `radar_tokens.first_detected_at` is written only by the successful Track
        Record admission insert and never updated afterwards, so reading it is
        reading the product record itself — no score, rank or category gate is
        duplicated here, and Karthik's universe cannot drift from what the
        Track Record page shows.

        Deliberately **not** the token's discovery time. A token first seen at
        10:00 that entered the Track Record at 10:20 is eligible for a wallet
        activated at 10:10, because the event Karthik trades is the admission.

        The anti-join against the ledger is an optimisation, not the guarantee —
        `uq_karthik_opportunities_wallet_mint` is the guarantee. Without the
        join every pass would re-examine every admission since activation, and
        the bounded batch would eventually never reach the newest ones.

        Ordered oldest admission first, with a mint tiebreak, so the batch is
        deterministic and the tail cannot starve.
        """
        decided = select(KarthikOpportunity.mint_address).where(
            KarthikOpportunity.wallet_id == wallet.id
        )
        return (
            await self._session.scalars(
                select(RadarToken)
                .where(
                    RadarToken.first_detected_at > wallet.activated_at,
                    RadarToken.first_detected_at <= as_of,
                    RadarToken.mint_address.not_in(decided),
                )
                .order_by(RadarToken.first_detected_at.asc(), RadarToken.mint_address.asc())
                .limit(limit)
            )
        ).all()

    async def opportunities_since_activation(self, wallet: KarthikWallet) -> int:
        """How many Track Record admissions have happened since activation.

        The denominator of the capture rate. Counted from the Track Record
        itself rather than from the ledger, so an admission Karthik has not yet
        reached is still counted as an opportunity that existed.
        """
        return (
            await self._session.scalar(
                select(func.count())
                .select_from(RadarToken)
                .where(RadarToken.first_detected_at > wallet.activated_at)
            )
        ) or 0

    # --- The decision ledger -------------------------------------------------

    async def claim(
        self,
        *,
        wallet: KarthikWallet,
        mint_address: str,
        track_record_at: datetime,
        decision: str,
        decided_at: datetime,
    ) -> bool:
        """Record one irreversible decision, returning whether this caller won.

        `False` means another pass, another worker or an earlier run of this one
        already decided this mint. The caller must then do nothing at all — that
        is what makes a duplicate Track Record event, a Celery retry and a
        worker restart produce one position rather than two.
        """
        result = await self._session.execute(
            insert(KarthikOpportunity)
            .values(
                wallet_id=wallet.id,
                mint_address=mint_address,
                track_record_at=track_record_at,
                decision=decision,
                decided_at=decided_at,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    KarthikOpportunity.wallet_id,
                    KarthikOpportunity.mint_address,
                ]
            )
            .returning(KarthikOpportunity.id)
        )
        return result.scalar_one_or_none() is not None

    async def skipped(
        self, wallet_id: uuid.UUID, *, limit: int = 200
    ) -> Sequence[KarthikOpportunity]:
        """The misses, newest first. Shown, because a capture rate needs them."""
        return (
            await self._session.scalars(
                select(KarthikOpportunity)
                .where(
                    KarthikOpportunity.wallet_id == wallet_id,
                    KarthikOpportunity.decision != "entered",
                )
                .order_by(
                    KarthikOpportunity.track_record_at.desc(),
                    KarthikOpportunity.mint_address.asc(),
                )
                .limit(limit)
            )
        ).all()

    async def decision_counts(self, wallet_id: uuid.UUID) -> dict[str, int]:
        rows = await self._session.execute(
            select(KarthikOpportunity.decision, func.count())
            .where(KarthikOpportunity.wallet_id == wallet_id)
            .group_by(KarthikOpportunity.decision)
        )
        return dict(rows.all())  # type: ignore[arg-type]

    # --- Positions -----------------------------------------------------------

    def _for_wallet(self, wallet_id: uuid.UUID) -> Select[tuple[KarthikPosition]]:
        return select(KarthikPosition).where(KarthikPosition.wallet_id == wallet_id)

    async def open_position(self, **values: Any) -> KarthikPosition | None:
        """Insert one position, or return `None` if the mint was already taken.

        The second half of exactly-once. Even a caller that skipped the ledger
        entirely cannot create a second Karthik position in a mint, because
        `uq_karthik_positions_wallet_mint` will not let it.
        """
        result = await self._session.execute(
            insert(KarthikPosition)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[KarthikPosition.wallet_id, KarthikPosition.mint_address]
            )
            .returning(KarthikPosition)
        )
        return result.scalar_one_or_none()

    async def open_positions(
        self, wallet_id: uuid.UUID, *, limit: int | None = None
    ) -> Sequence[KarthikPosition]:
        """Running positions, oldest watermark first.

        The order is the anti-starvation rule: a bounded batch taken in
        arbitrary heap order returns the same rows every cycle and the tail
        never advances.
        """
        statement = (
            self._for_wallet(wallet_id)
            .where(KarthikPosition.status == "open")
            .order_by(
                KarthikPosition.last_evaluated_at.asc(), KarthikPosition.mint_address.asc()
            )
        )
        if limit is not None:
            statement = statement.limit(limit)
        return (await self._session.scalars(statement)).all()

    async def closed_positions(self, wallet_id: uuid.UUID) -> Sequence[KarthikPosition]:
        """Every finished trade, newest first. Dead ones included, always."""
        return (
            await self._session.scalars(
                self._for_wallet(wallet_id)
                .where(KarthikPosition.status == "closed")
                .order_by(KarthikPosition.closed_at.desc(), KarthikPosition.mint_address.asc())
            )
        ).all()

    async def advance(
        self,
        position_id: uuid.UUID,
        *,
        peak_price: Decimal,
        last_evaluated_at: datetime,
        last_market_check_at: datetime | None,
    ) -> None:
        """Carry a still-open position's watermarks forward.

        Scoped to `status = 'open'` so a pass that raced a close cannot reopen
        the watermark on a settled trade.
        """
        from sqlalchemy import update

        await self._session.execute(
            update(KarthikPosition)
            .where(KarthikPosition.id == position_id, KarthikPosition.status == "open")
            .values(
                peak_price=peak_price,
                last_evaluated_at=last_evaluated_at,
                last_market_check_at=last_market_check_at,
            )
        )

    async def close(self, position_id: uuid.UUID, **values: Any) -> bool:
        """Settle one position, once.

        The `status = 'open'` predicate is the guard behind "a 2x printed after
        the target already closed the trade produces no second fill": a close
        against an already-closed row updates nothing and returns `False`.
        """
        from sqlalchemy import update

        result = await self._session.execute(
            update(KarthikPosition)
            .where(KarthikPosition.id == position_id, KarthikPosition.status == "open")
            .values(status="closed", **values)
            .returning(KarthikPosition.id)
        )
        return result.scalar_one_or_none() is not None

    # --- Accounting ----------------------------------------------------------

    async def committed_and_returned(self, wallet_id: uuid.UUID) -> tuple[Decimal, Decimal]:
        """Total capital committed to entries, and total returned by exits.

        Cash is derived from these two sums and the wallet's starting capital.
        Nothing stores a balance: a stored balance is a second source of truth
        that drifts the moment one write lands without the other, and a wallet
        whose balance disagrees with its own trades is worth less than none.
        """
        committed = (
            await self._session.scalar(
                select(func.coalesce(func.sum(KarthikPosition.cost_basis), 0)).where(
                    KarthikPosition.wallet_id == wallet_id
                )
            )
        ) or Decimal(0)
        returned = (
            await self._session.scalar(
                select(func.coalesce(func.sum(KarthikPosition.exit_proceeds_usd), 0)).where(
                    KarthikPosition.wallet_id == wallet_id,
                    KarthikPosition.status == "closed",
                )
            )
        ) or Decimal(0)
        return Decimal(committed), Decimal(returned)
