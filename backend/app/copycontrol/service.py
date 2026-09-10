"""CPY-02's book: mirror CPY-01's timing, choose the token at random.

Driven off `pumpfun_signals` rather than off the Helius feed directly. Those
rows are the durable record of what CPY-01 ACTUALLY did — `acted=True` carries
the position it opened or closed — so the control pairs against the strategy's
real behaviour rather than re-deriving it and risking a different answer. It
also means the control cannot act on a signal the strategy declined, which is
what keeps the two arms on the same trades.

Read-mostly with respect to pump.fun: this module never calls the leader feed,
never enrols a token on demand and never touches `app/pumpfun/`. It is a
consumer of that lab's ledger and nothing more.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, select

from app.copycontrol import spec
from app.core.logging import get_logger
from app.lab import execution
from app.lab.service import LabService
from app.models.lab import LabDecision, LabPosition, LabStrategy, LabTournament
from app.models.market import TokenEnrichmentState, TokenMarketSnapshot
from app.models.pumpfun import PumpfunSignal
from app.models.token import DiscoveredToken

logger = get_logger(__name__)

#: How fresh a snapshot must be for a token to be a candidate. The same 15
#: minutes `_mark` uses: a price older than that is not a market you can trade
#: against, and a control that buys at a stale price flatters itself.
CANDIDATE_FRESHNESS_MINUTES = 15

#: How far back the signal scan looks. Long enough that a worker outage cannot
#: lose a leader trade, short enough that the scan stays small.
SIGNAL_WINDOW_HOURS = 48

#: A leader BUY that started a position. Mirrored by opening one.
OPENED = ("opened",)
#: A leader BUY that SCALED INTO a position already held. Deliberately NOT
#: mirrored from the signal — `_reconcile` reads the resulting STATE instead,
#: which has no window and therefore no way to miss one permanently.
ADDED = ("added",)
#: A leader SELL that ENDED the position. Mirrored by closing the pair.
CLOSED = ("closed",)

#: A leader SELL that released only PART of a position. Deliberately NOT
#: mirrored from the signal, for the same reason as `ADDED` — `_reconcile`
#: matches the pair's remaining fraction from state instead.
TRIMMED = ("trimmed",)


class CopyControlService:
    """The control arm. One tick mirrors whatever CPY-01 did since the last."""

    def __init__(self, session) -> None:
        self._session = session
        self._lab = LabService(session, registry=spec)

    # --- pairing ------------------------------------------------------------

    async def _unmirrored(self, t: LabTournament, now: datetime
                          ) -> list[PumpfunSignal]:
        """Acted leader signals this arm has not yet answered.

        Bounded by the control's own `valid_from`: a control cannot be run
        retroactively, so CPY-01's earlier trades are deliberately out of
        reach rather than back-filled at today's prices.
        """
        # Windowed as well as watermarked. Re-examining an already-handled
        # signal is harmless — every path is idempotent — but a fixed LIMIT
        # over an unbounded history would eventually fill with old signals and
        # starve the new ones, which fails silently as "the control stopped
        # trading".
        window = now - timedelta(hours=SIGNAL_WINDOW_HOURS)
        floor = max(t.valid_from, window)
        rows = (await self._session.execute(
            select(PumpfunSignal)
            .where(PumpfunSignal.acted.is_(True),
                   PumpfunSignal.seen_at >= floor)
            .order_by(PumpfunSignal.leader_at)
            .limit(200)
        )).scalars().all()
        return list(rows)

    async def _any_paired(self, leader_position_id) -> bool:
        """Has this arm EVER answered that leader position, open or closed?"""
        if leader_position_id is None:
            return False
        return (await self._session.execute(
            select(LabPosition.id)
            .join(LabDecision, LabDecision.id == LabPosition.decision_id)
            .where(LabPosition.strategy_id == "CPY-02",
                   LabDecision.features["leader_position_id"].astext
                   == str(leader_position_id))
            .limit(1)
        )).first() is not None

    async def _paired_position(self, leader_position_id: uuid.UUID
                               ) -> LabPosition | None:
        """This arm's position that answers a given CPY-01 position."""
        return (await self._session.execute(
            select(LabPosition)
            .join(LabDecision, LabDecision.id == LabPosition.decision_id)
            .where(LabPosition.strategy_id == "CPY-02",
                   LabPosition.status == "open",
                   LabDecision.features["leader_position_id"].astext
                   == str(leader_position_id))
        )).scalars().first()

    # --- choosing --------------------------------------------------------

    async def _candidates(self, *, exclude: set[str], now: datetime
                          ) -> list[tuple[str, uuid.UUID, Decimal, Decimal]]:
        """Priceable pump.fun tokens this arm could buy right now.

        Ordered by mint so the pool is deterministic for a given instant; the
        SEED does the choosing, not the ordering. Freshness is the only filter
        beyond provenance — any further condition would make this a strategy.
        """
        cut = now - timedelta(minutes=CANDIDATE_FRESHNESS_MINUTES)
        latest = (
            select(TokenMarketSnapshot.mint_address,
                   func.max(TokenMarketSnapshot.captured_at).label("at"))
            .where(TokenMarketSnapshot.captured_at >= cut,
                   TokenMarketSnapshot.suspect.is_not(True))
            .group_by(TokenMarketSnapshot.mint_address)
            .subquery()
        )
        rows = (await self._session.execute(
            select(TokenMarketSnapshot.mint_address,
                   TokenMarketSnapshot.token_id,
                   TokenMarketSnapshot.price_usd,
                   TokenMarketSnapshot.liquidity_usd)
            .join(latest,
                  and_(latest.c.mint_address == TokenMarketSnapshot.mint_address,
                       latest.c.at == TokenMarketSnapshot.captured_at))
            .join(DiscoveredToken,
                  DiscoveredToken.id == TokenMarketSnapshot.token_id)
            # `delisted_at` lives on TokenEnrichmentState, NOT on
            # DiscoveredToken. An outer join because a token with no enrichment
            # row yet is un-stamped rather than dead, and excluding it would
            # bias the control's pool towards older names — a selection rule
            # smuggled in through a JOIN.
            .outerjoin(TokenEnrichmentState,
                       TokenEnrichmentState.token_id == TokenMarketSnapshot.token_id)
            .where(TokenMarketSnapshot.price_usd > 0,
                   TokenMarketSnapshot.liquidity_usd > 0,
                   TokenEnrichmentState.delisted_at.is_(None),
                   DiscoveredToken.source_program.in_(
                       self._lab._pumpfun_programs()))
            .order_by(TokenMarketSnapshot.mint_address)
        )).all()
        return [(m, tid, px, liq) for m, tid, px, liq in rows
                if m not in exclude]

    @staticmethod
    def _pick(candidates: list, signature: str):
        """Choose one, reproducibly, from the leader's signature.

        Seeded rather than free so the ledger can be replayed: "why that token"
        is answerable months later from the signature alone. A control nobody
        can audit is not evidence, and an unseeded `random` would make every
        pick a fact about a process that no longer exists.
        """
        seed = int(hashlib.sha256(signature.encode()).hexdigest()[:16], 16)
        return random.Random(seed).choice(candidates)

    # --- acting -----------------------------------------------------------

    async def _open(self, row: LabStrategy, sig: PumpfunSignal,
                    now: datetime) -> str:
        # IDEMPOTENT BY STATE, not by a ledger row.
        #
        # `uq_lab_decision_per_checkpoint` keys a decision on the arm, the mint
        # and the checkpoint, so a decision cannot serve as a per-signal ledger — a marker for the add
        # and the close of one pair collide on the leader's mint. Deriving
        # "already handled" from the book instead is stronger anyway: a ledger
        # write that fails leaves capital spendable twice, whereas a position
        # that exists is the fact itself. `_add` is idempotent for the same
        # reason (its increment goes to zero) and so is `_close` (it looks for
        # an OPEN pair).
        if await self._any_paired(sig.position_id):
            return "already_mirrored"

        leader_pos = (await self._session.execute(
            select(LabPosition).where(LabPosition.id == sig.position_id)
        )).scalars().first()
        if leader_pos is None:
            return "leader_position_missing"

        # SIZE IS READ FROM THE PAIR, never from this registry. CPY-01 moved
        # from $20 x 5 to $10 x 10 between versions; a hardcoded size here would
        # have made the arms differ in size as well as in token, and no
        # difference between them could then be attributed to either.
        size = leader_pos.size_usd or spec.FALLBACK_SIZE_USD
        if row.cash < size:
            return "insufficient_cash"

        held = (await self._session.execute(
            select(LabPosition).where(LabPosition.strategy_row_id == row.id,
                                      LabPosition.status == "open")
        )).scalars().all()
        if len(held) >= spec.MAX_CONCURRENT:
            return "max_concurrent"

        exclude = {p.mint_address for p in held} | {sig.mint_address}
        candidates = await self._candidates(exclude=exclude, now=now)
        if not candidates:
            return "no_candidates"
        mint, token_id, price, liq = self._pick(candidates, sig.signature)

        qty = execution.buy_quantity(size, price, liq)
        if qty is None or qty <= 0:
            return "unpriceable"

        decision = LabDecision(
            strategy_row_id=row.id, strategy_id=row.strategy_id,
            mint_address=mint, token_id=token_id,
            checkpoint_at=sig.leader_at, checkpoint_minutes=0,
            decided_at=now, eligible=True,
            features={
                # The pairing. Everything needed to replay the choice and to
                # find the CPY-01 position this one answers.
                "leader_signature": sig.signature,
                "leader_position_id": str(sig.position_id),
                "leader_mint": sig.mint_address,
                "chosen_at_random_from": len(candidates),
                "size_copied_from_pair": str(size),
            },
            requested_size_usd=size,
        )
        self._session.add(decision)
        await self._session.flush()

        row.cash -= size
        pos = LabPosition(
            decision_id=decision.id,
            strategy_row_id=row.id, strategy_id=row.strategy_id,
            mint_address=mint, token_id=token_id,
            opened_at=now, entry_price=price, entry_liquidity_usd=liq,
            size_usd=size, quantity=qty, quantity_remaining=qty,
            banked_proceeds_usd=Decimal(0), status="open",
            peak_exec_multiple=Decimal(1), last_exec_multiple=Decimal(1),
            last_open_value_usd=size, entry_source="copy_control",
        )
        self._session.add(pos)
        await self._session.flush()
        return "opened"

    async def _price(self, mint: str, now: datetime):
        """Latest fresh print for one mint, or None."""
        cut = now - timedelta(minutes=CANDIDATE_FRESHNESS_MINUTES)
        return (await self._session.execute(
            select(TokenMarketSnapshot.price_usd,
                   TokenMarketSnapshot.liquidity_usd)
            .where(TokenMarketSnapshot.mint_address == mint,
                   TokenMarketSnapshot.captured_at >= cut,
                   TokenMarketSnapshot.suspect.is_not(True),
                   TokenMarketSnapshot.price_usd > 0,
                   TokenMarketSnapshot.liquidity_usd > 0)
            .order_by(TokenMarketSnapshot.captured_at.desc())
        )).first()

    async def _top_up(self, row: LabStrategy, mine: LabPosition,
                      leader_pos: LabPosition, now: datetime) -> str:
        """Bring one paired position up to the capital its pair now holds.

        Driven by RECONCILIATION rather than by an `added` signal — see
        `_reconcile`. Mirroring an `added` as a fresh open was a real defect,
        and it broke the design in both of the ways it is supposed to be
        impossible to break.
        `_add` on the pumpfun side grows `size_usd` CUMULATIVELY on one row, so
        by the time an `added` signal exists that field is the running total:
        opening at it deployed the total AGAIN on top of what was already there.
        Measured, at a $10 unit, CPY-01 held $20 in one position while this arm
        held $30 across two — differing in capital AND in count, and reaching
        the whole $100 book against the pair's $40 at a four-unit cap.

        It also broke the pairing itself. `_paired_position` resolves one row
        per pair, so several control rows against one leader position would
        leave all but one of them with nothing able to close it.

        The increment is the DIFFERENCE between what the pair now holds and what
        this arm has already put against it — not a unit size read from
        anywhere. That needs no import from `app.pumpfun`, survives any future
        change to their unit, and self-corrects: a tick missed while the leader
        scaled in twice is caught up by the next one rather than lost.
        """
        increment = (leader_pos.size_usd or Decimal(0)) - mine.size_usd
        if increment <= 0:
            return "already_matched"
        if row.cash < increment:
            return "insufficient_cash"
        got = await self._price(mine.mint_address, now)
        if got is None:
            return "unpriceable"
        price, liq = got
        qty = execution.buy_quantity(increment, price, liq)
        if qty is None or qty <= 0:
            return "unpriceable"

        # Averages in, exactly as the pumpfun `_add` does: stake, quantity and
        # entry price all move to the blended position. `uq_lab_position_once`
        # allows one row per (strategy, mint) anyway.
        row.cash -= increment
        mine.size_usd += increment
        mine.quantity += qty
        mine.quantity_remaining += qty
        mine.entry_price = mine.size_usd / mine.quantity
        mine.last_open_value_usd = mine.size_usd
        await self._session.flush()
        return "added"

    async def _close(self, sig: PumpfunSignal, now: datetime) -> str:
        """Close this arm's paired position when the leader closes his.

        Through `close_manually` with an explicit reason, so the fill goes
        through the same `_mark`, stale guard, glitch band and depth impact the
        strategies get. The reason is `paired_close`, NOT the manual tag: this
        exit followed the control's own rule — hold exactly as long as the pair
        — and tagging it as a hand sell would wrongly exclude the control's
        results from every comparison that filters manual exits out.
        """
        if sig.position_id is None:
            return "no_pair_recorded"
        mine = await self._paired_position(sig.position_id)
        if mine is None:
            return "no_paired_position"
        out = await self._lab.close_manually(
            position_id=mine.id, now=now, actor="cpy02_pair",
            reason="paired_close",
        )
        return "closed" if out.get("closed") else out.get("reason", "refused")

    async def _reconcile(self, row: LabStrategy, now: datetime) -> dict[str, int]:
        """Top up every open pair that its leader has since scaled into.

        This REPLACES mirroring the `added` signal, and is strictly stronger
        than it. A signal-driven add only ever fires while the signal is inside
        the scan window, so a control that was down longer than the window
        stayed permanently under-sized against that pair — silently, and with
        no later signal guaranteed to correct it. The comparison the whole arm
        exists to support would then be quietly wrong for that token, which is
        the worst failure available to a control.

        Reconciling from state has no window at all: the pair's `size_usd` and
        this arm's are both facts, and their difference is the answer however
        long ago it arose. It also deletes a code path rather than adding one —
        `added` signals now need no handling, because the state they describe
        is what is being read.

        The cost is that a top-up after an outage happens at the CURRENT price
        rather than the leader's. That is a real difference and it is the right
        trade: an arm whose timing already slipped by an outage is better off
        matching capital late than never matching it at all, because equity is
        what the two arms are compared on.
        """
        pairs = (await self._session.execute(
            select(LabPosition,
                   LabDecision.features["leader_position_id"].astext)
            .join(LabDecision, LabDecision.id == LabPosition.decision_id)
            .where(LabPosition.strategy_row_id == row.id,
                   LabPosition.status == "open")
        )).all()
        counts: dict[str, int] = {}
        for mine, leader_id in pairs:
            if not leader_id:
                continue
            leader_pos = (await self._session.execute(
                select(LabPosition).where(LabPosition.id == uuid.UUID(leader_id))
            )).scalars().first()
            if leader_pos is None:
                continue
            if (leader_pos.size_usd or Decimal(0)) > mine.size_usd:
                outcome = await self._top_up(row, mine, leader_pos, now)
                counts[outcome] = counts.get(outcome, 0) + 1
                continue
            outcome = await self._match_exposure(mine, leader_pos, now)
            if outcome:
                counts[outcome] = counts.get(outcome, 0) + 1
        return counts

    async def _match_exposure(self, mine: LabPosition, leader_pos: LabPosition,
                              now: datetime) -> str | None:
        """Release the same FRACTION of the pair that the leader has released.

        He sells a name in roughly 1.9 tranches, and CPY-01 mirrors that by
        TRIMMING on every sell but the last. Treating a `trimmed` signal as a
        close — which this arm did — exited the control's whole position on his
        first partial sell.

        That is not a small asymmetry. It is precisely the bias pumpfun v1.1.0
        was fixed to remove: exiting while he is still holding biases the record
        against the position that RUNS, which is the only outcome the experiment
        is trying to catch. Having it in the control rather than the strategy is
        worse than having it in neither, because it penalises the control
        systematically on exactly the trades that decide the comparison.

        Matched from state rather than from the signal, for the same reason as
        the top-up: a fraction is a fact about the two positions, so no trim can
        be missed by being outside a scan window.
        """
        if not leader_pos.quantity or not mine.quantity:
            return None
        theirs = leader_pos.quantity_remaining / leader_pos.quantity
        ours = mine.quantity_remaining / mine.quantity
        # Only ever SELL to catch up. A pair that holds proportionally more than
        # this arm is not a reason to buy back in — the leader scaling in is
        # handled by `_top_up`, and re-buying a slice already sold would invent
        # a trade he never made.
        if theirs >= ours:
            return None
        # Fraction OF WHAT REMAINS, so the arm lands on his remaining share.
        fraction = (ours - theirs) / ours
        if fraction <= 0:
            return None
        out = await self._lab.trim_manually(
            position_id=mine.id, now=now, actor="cpy02_pair",
            fraction=min(fraction, Decimal(1)),
        )
        return "trimmed" if out.get("trimmed") else out.get("reason", "trim_refused")

    # --- the beat -----------------------------------------------------------

    async def tick(self, *, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(UTC)
        t = await self._lab.activate(valid_from=now)
        row = (await self._session.execute(
            select(LabStrategy).where(
                LabStrategy.spec_hash == spec.SPEC_HASH)
        )).scalars().first()
        if row is None:
            return {"skipped": "not_activated"}

        counts: dict[str, int] = {}
        for sig in await self._unmirrored(t, now):
            if sig.outcome in OPENED and sig.side == "buy":
                outcome = await self._open(row, sig, now)
            elif sig.outcome in CLOSED and sig.side == "sell":
                outcome = await self._close(sig, now)
            else:
                outcome = "not_mirrorable"
            counts[outcome] = counts.get(outcome, 0) + 1

        # AFTER the signals, so a pair opened this same tick is topped up in it
        # rather than a minute later.
        for k, v in (await self._reconcile(row, now)).items():
            counts[k] = counts.get(k, 0) + v

        settled = await self._lab.settle(now=now)
        await self._lab.record_equity(now=now)
        equity = await self._lab.equity(row)
        if counts.get("opened") or counts.get("closed"):
            logger.info("copycontrol_tick", **counts, equity=str(equity))
        return {"mirrored": counts, "settled": settled, "equity": str(equity),
                "watching_from": t.valid_from.isoformat()}
