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
from app.models.paper_research import PaperDecisionSnapshot
from app.models.radar import RadarToken
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

    async def restore_generation_two(
        self, *, resumed_at: datetime, archive_live_reason: str
    ) -> PaperWallet:
        """Atomically archive the current live experiment and resume Gen 2.

        This intentionally names no position or audit column: restoring a
        record may switch its wallet state, never rewrite its trades.
        """
        target = await self._session.scalar(
            select(PaperWallet)
            .where(
                PaperWallet.generation == 2,
                PaperWallet.strategy_id == "trailing_stop_25_v1",
                PaperWallet.strategy_version == "1.0.0",
            )
            .with_for_update()
        )
        if target is None or target.archived_at is None:
            raise RuntimeError("Generation 2 trailing-stop wallet is not archived")

        live = await self._session.scalar(
            select(PaperWallet).where(PaperWallet.archived_at.is_(None)).with_for_update()
        )
        if live is not None and live.id != target.id:
            if live.generation not in {5, 6}:
                raise RuntimeError("refusing to archive an unexpected live paper wallet")
            await self._session.execute(
                update(PaperWallet)
                .where(PaperWallet.id == live.id, PaperWallet.archived_at.is_(None))
                .values(archived_at=resumed_at, archive_reason=archive_live_reason)
            )

        previous_archive_at = target.archived_at
        previous_archive_reason = target.archive_reason
        await self._session.execute(
            update(PaperWallet)
            .where(PaperWallet.id == target.id, PaperWallet.archived_at.is_not(None))
            .values(
                archived_at=None,
                archive_reason=None,
                resumed_at=resumed_at,
                resume_watermark_at=resumed_at,
                restored_archive_at=previous_archive_at,
                restored_archive_reason=previous_archive_reason,
            )
        )
        await self._session.flush()
        restored = await self.live_wallet()
        if restored is None or restored.id != target.id:  # pragma: no cover
            raise RuntimeError("Generation 2 restoration did not produce the live wallet")
        return restored

    async def lock_wallet(self, wallet_id: uuid.UUID) -> None:
        """Serialize allocation so concurrent review workers cannot overspend."""
        await self._session.execute(
            select(PaperWallet.id).where(PaperWallet.id == wallet_id).with_for_update()
        )

    async def claim_all_scanned_entry_decision(
        self,
        *,
        wallet: PaperWallet,
        mint_address: str,
        token_id: uuid.UUID,
        detected_at: datetime,
        decision: str,
        reason: str | None = None,
    ) -> bool:
        """Claim one irreversible entry decision per raw scanner discovery.

        A cash refusal is terminal for this generation, rather than a deferred
        order that could silently buy an old token after a later exit.
        """
        source_key = f"paper-all-scanned:{wallet.id}:{mint_address}"
        result = await self._session.execute(
            insert(PaperDecisionSnapshot)
            .values(
                decision_source="paper",
                source_decision_key=source_key,
                wallet_code=f"generation-{wallet.generation}",
                strategy_id=wallet.strategy_id,
                strategy_version=wallet.strategy_version,
                mint_address=mint_address,
                token_id=token_id,
                decided_at=detected_at,
                decision=decision,
                reason_codes=[] if reason is None else [reason],
                market_features={},
                radar_state={},
                observation_history={},
                availability={},
            )
            .on_conflict_do_nothing(
                index_elements=[
                    PaperDecisionSnapshot.decision_source,
                    PaperDecisionSnapshot.source_decision_key,
                ]
            )
            .returning(PaperDecisionSnapshot.id)
        )
        return result.scalar_one_or_none() is not None

    async def track_record_admissions_after(
        self, *, watermark: datetime, limit: int, as_of: datetime | None = None
    ) -> Sequence[RadarToken]:
        """Canonical Track Record additions after a forward-wallet watermark.

        ``RadarToken.first_detected_at`` is written only by the successful
        Track Record admission insert and never updated afterwards.  Reading it
        directly keeps the paper universe identical to the product record,
        without duplicating score, rank, or category gates here.
        """
        predicates = [RadarToken.first_detected_at > watermark]
        if as_of is not None:
            predicates.append(RadarToken.first_detected_at <= as_of)
        return (
            await self._session.scalars(
                select(RadarToken)
                .where(*predicates)
                .order_by(RadarToken.first_detected_at.asc(), RadarToken.mint_address.asc())
                .limit(limit)
            )
        ).all()

    async def claim_track_record_entry_decision(
        self,
        *,
        wallet: PaperWallet,
        admission: RadarToken,
        decision: str,
        reason: str | None = None,
    ) -> bool:
        """Claim one irreversible Generation 6 decision per Track Record mint."""
        source_key = f"paper-track-record:{wallet.id}:{admission.mint_address}"
        result = await self._session.execute(
            insert(PaperDecisionSnapshot)
            .values(
                decision_source="paper",
                source_decision_key=source_key,
                wallet_code=f"generation-{wallet.generation}",
                strategy_id=wallet.strategy_id,
                strategy_version=wallet.strategy_version,
                mint_address=admission.mint_address,
                token_id=admission.token_id,
                decided_at=admission.first_detected_at,
                decision=decision,
                reason_codes=[] if reason is None else [reason],
                market_features={},
                radar_state={},
                observation_history={},
                availability={},
            )
            .on_conflict_do_nothing(
                index_elements=[
                    PaperDecisionSnapshot.decision_source,
                    PaperDecisionSnapshot.source_decision_key,
                ]
            )
            .returning(PaperDecisionSnapshot.id)
        )
        return result.scalar_one_or_none() is not None

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
        last_market_check_at: datetime | None = None,
    ) -> None:
        """Move the high-water marks forward without closing."""
        values: dict[str, Any] = {
            "peak_price": func.greatest(PaperPosition.peak_price, peak_price),
            "last_evaluated_at": last_evaluated_at,
        }
        if last_market_check_at is not None:
            values["last_market_check_at"] = last_market_check_at
            
        await self._session.execute(
            update(PaperPosition)
            .where(
                PaperPosition.id == position_id,
                PaperPosition.status == PositionStatus.OPEN.value,
                PaperPosition.last_evaluated_at <= last_evaluated_at,
            )
            .values(**values)
        )

    async def advance_activated_trail(
        self,
        position_id: uuid.UUID,
        *,
        peak_price: Decimal,
        trailing_stop_price: Decimal | None,
        last_evaluated_at: datetime,
        activated_at: datetime | None = None,
        activation_observed_price: Decimal | None = None,
        last_market_check_at: datetime | None = None,
    ) -> None:
        """Advance activation/trail state without allowing it to move backwards."""
        values: dict[str, Any] = {
            "peak_price": func.greatest(PaperPosition.peak_price, peak_price),
            "last_evaluated_at": last_evaluated_at,
        }
        if last_market_check_at is not None:
            values["last_market_check_at"] = last_market_check_at
            
        if trailing_stop_price is not None:
            values["trailing_stop_price"] = func.greatest(
                func.coalesce(PaperPosition.trailing_stop_price, Decimal(0)),
                trailing_stop_price,
            )
        if activated_at is not None:
            values["trailing_activated_at"] = func.coalesce(
                PaperPosition.trailing_activated_at, activated_at
            )
            values["trailing_activation_observed_price"] = func.coalesce(
                PaperPosition.trailing_activation_observed_price, activation_observed_price
            )
        await self._session.execute(
            update(PaperPosition)
            .where(
                PaperPosition.id == position_id,
                PaperPosition.status == PositionStatus.OPEN.value,
                PaperPosition.last_evaluated_at <= last_evaluated_at,
            )
            .values(**values)
        )

    async def close(
        self,
        position_id: uuid.UUID,
        *,
        exit_price: Decimal,
        closed_at: datetime,
        exit_reason: str,
        peak_price: Decimal,
        manual_action_at: datetime | None = None,
        exit_observed_price: Decimal | None = None,
        exit_execution_model_version: str | None = None,
        exit_execution_quote: dict[str, object] | None = None,
        exit_execution_quoted_at: datetime | None = None,
        exit_execution_context_slot: int | None = None,
        exit_execution_price_impact_pct: Decimal | None = None,
        exit_execution_fee_usd: Decimal | None = None,
        exit_execution_route: str | None = None,
        exit_execution_confidence: str | None = None,
        exit_execution_fallback_reason: str | None = None,
        trailing_trigger_price: Decimal | None = None,
        trailing_trigger_observed_price: Decimal | None = None,
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
                exit_observed_price=exit_observed_price,
                closed_at=closed_at,
                exit_reason=exit_reason,
                manual_action_at=manual_action_at,
                exit_execution_model_version=exit_execution_model_version,
                exit_execution_quote=exit_execution_quote,
                exit_execution_quoted_at=exit_execution_quoted_at,
                exit_execution_context_slot=exit_execution_context_slot,
                exit_execution_price_impact_pct=exit_execution_price_impact_pct,
                exit_execution_fee_usd=exit_execution_fee_usd,
                exit_execution_route=exit_execution_route,
                exit_execution_confidence=exit_execution_confidence,
                exit_execution_fallback_reason=exit_execution_fallback_reason,
                trailing_trigger_price=trailing_trigger_price,
                trailing_trigger_observed_price=trailing_trigger_observed_price,
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
        self, wallet_id: uuid.UUID, *, limit: int | None = 100, offset: int = 0
    ) -> Sequence[PaperTradeAudit]:
        """The log, newest exit first. Losers are never filtered out."""
        statement = (
            select(PaperTradeAudit)
            .where(PaperTradeAudit.wallet_id == wallet_id)
            .order_by(PaperTradeAudit.exit_at.desc(), PaperTradeAudit.mint_address.asc())
            .offset(offset)
        )
        if limit is not None:
            statement = statement.limit(limit)
        return (await self._session.scalars(statement)).all()

    async def audits_for_position_ids(
        self, position_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, PaperTradeAudit]:
        """Return the immutable close record for each requested position.

        The closed-positions table must show the same settled costs as the
        permanent record, rather than rebuilding fees or price impact from a
        later market snapshot. A position has at most one audit row by the
        database constraint, so the map is an unambiguous read model.
        """
        unique_ids = list(dict.fromkeys(position_ids))
        if not unique_ids:
            return {}
        rows = await self._session.scalars(
            select(PaperTradeAudit).where(PaperTradeAudit.position_id.in_(unique_ids))
        )
        return {row.position_id: row for row in rows.all()}

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
