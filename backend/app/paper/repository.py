"""Paper wallet database access.

The package's only I/O seam besides `service.py`, `scheduler.py` and `api.py`.
Everything above this line is pure.

Four guarantees are enforced here rather than in application logic:

* **A token is entered once, ever.** `open_position` inserts with
  `ON CONFLICT DO NOTHING` against `uq_paper_positions_wallet_mint` and returns
  `None` when the row already exists. Two evaluators racing the same Radar page
  cannot double-buy, and a re-run of the same pass is a no-op.
* **The entry block is never rewritten.** The update statements below touch only
  the evaluator's columns; nothing in this file can move an entry price, a
  trailing distance or a size after the fact.
* **Only the live wallet is ever advanced.** Every wallet read filters on
  `archived_at IS NULL`, so an archived generation cannot be opened into, closed
  out of, or mixed into a figure. Reading an archive is a separate method with a
  separate name.
* **The audit log is append-only.** `record_audit` is one INSERT with
  `ON CONFLICT DO NOTHING`. There is no UPDATE and no DELETE against
  `paper_trade_audit` anywhere in this codebase, which is what makes "nothing is
  ever overwritten" checkable rather than merely intended.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.paper import PaperPosition, PaperTradeAudit, PaperWallet
from app.paper.models import PositionStatus


class PaperRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- Wallet --------------------------------------------------------------

    async def live_wallet(self) -> PaperWallet | None:
        """The one wallet that is not archived, or `None` before the first pass.

        No strategy filter. `uq_paper_wallets_live` guarantees at most one row
        satisfies this, so "the live wallet" is a fact about the database rather
        than a row picked by whichever id the configuration happened to name —
        which is what stops a mistyped setting from quietly starting a second
        track record beside the published one.
        """
        found: PaperWallet | None = await self._session.scalar(
            select(PaperWallet).where(PaperWallet.archived_at.is_(None))
        )
        return found

    async def archived_wallets(self) -> Sequence[PaperWallet]:
        """Every retired generation, newest first. Read-only, by construction.

        Nothing in this class writes to a wallet whose `archived_at` is set, and
        nothing advances positions that belong to one.
        """
        return (
            await self._session.scalars(
                select(PaperWallet)
                .where(PaperWallet.archived_at.is_not(None))
                .order_by(PaperWallet.generation.desc())
            )
        ).all()

    async def ensure_wallet(
        self,
        *,
        strategy_id: str,
        strategy_version: str,
        starting_balance: Decimal,
        generation: int,
        started_at: datetime,
    ) -> PaperWallet:
        """Get the live wallet, creating it once if there is none.

        Concurrency-safe rather than check-then-insert: two workers starting
        together would otherwise both see no wallet and both insert one, and the
        live-wallet index would fail the second mid-transaction. `ON CONFLICT DO
        NOTHING` followed by a read resolves either way to the same single row.

        `starting_balance` and `started_at` are only ever applied at creation.
        Every return and every benchmark is measured against them, so changing
        the setting later must not restate results already published — an
        existing wallet keeps the capital and the start instant it launched with.

        **An existing live wallet is returned whatever strategy it runs.** A
        configuration change is not a reset: relaunching under new rules means
        archiving this wallet deliberately, which is an operation with a record,
        not a side effect of an environment variable.
        """
        existing = await self.live_wallet()
        if existing is not None:
            return existing

        await self._session.execute(
            insert(PaperWallet)
            .values(
                strategy_id=strategy_id,
                strategy_version=strategy_version,
                starting_balance=starting_balance,
                generation=generation,
                started_at=started_at,
            )
            # Against the live index rather than the identity constraint: the
            # race being defended is "two workers both found no live wallet".
            .on_conflict_do_nothing()
        )
        await self._session.flush()
        wallet = await self.live_wallet()
        if wallet is None:  # pragma: no cover - the insert above guarantees it
            raise RuntimeError("the live paper wallet could not be created")
        return wallet

    async def next_generation(self) -> int:
        """One past the highest generation **any** wallet has ever launched.

        Counted across every wallet, not per strategy. The generation is how a
        reader refers to a launch — "the V2 wallet" is the second wallet this
        platform ran, whatever rules it followed. Numbering per strategy would
        have made the Sprint 30 relaunch "v1" because its rule was new, which is
        the opposite of what the number is for.

        Read from the table rather than from configuration: a constant in code
        would collide the second time the wallet is relaunched.
        """
        highest = await self._session.scalar(select(func.max(PaperWallet.generation)))
        return int(highest or 0) + 1

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
        self,
        wallet_id: uuid.UUID,
        *,
        limit: int | None = None,
        mints: Sequence[str] | None = None,
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
        if mints is not None:
            unique = list(dict.fromkeys(mints))
            if not unique:
                return []
            statement = statement.where(PaperPosition.mint_address.in_(unique))
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

    async def open_mints(self, wallet_id: uuid.UUID) -> set[str]:
        """The mints held right now.

        Separate from `held_mints` because the two refusals are different facts:
        "already held" is a position a reader can see on the page, and "already
        traded" is a closed one they have to look in the record for. Reporting
        them as one number would make an idle wallet look like a busy one.
        """
        rows = await self._session.scalars(
            select(PaperPosition.mint_address).where(
                PaperPosition.wallet_id == wallet_id,
                PaperPosition.status == PositionStatus.OPEN.value,
            )
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
            .where(
                PaperPosition.id == position_id,
                PaperPosition.status == PositionStatus.OPEN.value,
                PaperPosition.last_evaluated_at <= last_evaluated_at,
            )
            .values(
                # A delayed duplicate may only preserve or raise the running
                # high. It can never rewind a trailing stop after a newer pass
                # already observed a higher price.
                peak_price=func.greatest(PaperPosition.peak_price, peak_price),
                last_evaluated_at=last_evaluated_at,
            )
        )

    async def close(
        self,
        position_id: uuid.UUID,
        *,
        exit_price: Decimal,
        closed_at: datetime,
        exit_reason: str,
        peak_price: Decimal,
    ) -> bool:
        """Record a close, once.

        Guarded on `status = 'open'` rather than on the id alone, so a duplicate
        pass over the same position cannot rewrite an exit that already
        happened. A closed trade is part of the permanent record.
        """
        result = await self._session.execute(
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
            .returning(PaperPosition.id)
        )
        return result.scalar_one_or_none() is not None

    # --- The permanent record ------------------------------------------------

    async def record_audit(
        self, *, position_id: uuid.UUID, wallet_id: uuid.UUID, **values: Any
    ) -> bool:
        """Write one trade into the audit log, once. Returns whether it was new.

        **This is the only statement in the codebase that writes
        `paper_trade_audit`, and it is an INSERT.** There is no update path and
        no delete path, so "nothing may ever be overwritten" is a property of
        the code rather than a policy someone has to remember. A repeated close
        conflicts on `uq_paper_trade_audit_position` and does nothing.
        """
        result = await self._session.execute(
            insert(PaperTradeAudit)
            .values(position_id=position_id, wallet_id=wallet_id, **values)
            .on_conflict_do_nothing(index_elements=[PaperTradeAudit.position_id])
            .returning(PaperTradeAudit.id)
        )
        return result.scalar_one_or_none() is not None

    async def audited_position_ids(self, wallet_id: uuid.UUID) -> set[str]:
        """Which of a wallet's positions already have a record.

        Read before writing so the common case — every closed trade already
        audited — costs one query instead of one conflicting insert per trade.
        The unique index is still the guarantee.
        """
        rows = await self._session.scalars(
            select(PaperTradeAudit.position_id).where(PaperTradeAudit.wallet_id == wallet_id)
        )
        return {str(row) for row in rows.all()}

    async def audit_log(
        self, wallet_id: uuid.UUID, *, limit: int = 100, offset: int = 0
    ) -> Sequence[PaperTradeAudit]:
        """The log, newest exit first. Losers are never filtered out."""
        return (
            await self._session.scalars(
                select(PaperTradeAudit)
                .where(PaperTradeAudit.wallet_id == wallet_id)
                .order_by(PaperTradeAudit.exit_at.desc(), PaperTradeAudit.mint_address.asc())
                .offset(offset)
                .limit(limit)
            )
        ).all()

    async def audit_count(self, wallet_id: uuid.UUID) -> int:
        return (
            await self._session.scalar(
                select(func.count())
                .select_from(PaperTradeAudit)
                .where(PaperTradeAudit.wallet_id == wallet_id)
            )
            or 0
        )

    async def position_counts(self, wallet_id: uuid.UUID) -> dict[str, int]:
        """Open and closed counts for one wallet, without loading its rows.

        Used by the archive view, which reports how many trades a retired
        generation holds and has no reason to read them all.
        """
        rows = await self._session.execute(
            select(PaperPosition.status, func.count())
            .where(PaperPosition.wallet_id == wallet_id)
            .group_by(PaperPosition.status)
        )
        return {status: int(count) for status, count in rows.all()}
