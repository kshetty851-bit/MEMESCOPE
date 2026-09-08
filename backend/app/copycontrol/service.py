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

#: Outcomes on a leader BUY that mean CPY-01 put money to work.
OPENED = ("opened", "added")
#: Outcomes on a leader SELL that mean CPY-01 took money off the table.
CLOSED = ("closed", "trimmed")


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
        mirrored = select(LabDecision.features["leader_signature"].astext).where(
            LabDecision.strategy_id == "CPY-02"
        )
        rows = (await self._session.execute(
            select(PumpfunSignal)
            .where(PumpfunSignal.acted.is_(True),
                   PumpfunSignal.seen_at >= t.valid_from,
                   PumpfunSignal.signature.not_in(mirrored))
            .order_by(PumpfunSignal.leader_at)
            .limit(50)
        )).scalars().all()
        return list(rows)

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

        settled = await self._lab.settle(now=now)
        await self._lab.record_equity(now=now)
        equity = await self._lab.equity(row)
        if counts.get("opened") or counts.get("closed"):
            logger.info("copycontrol_tick", **counts, equity=str(equity))
        return {"mirrored": counts, "settled": settled, "equity": str(equity),
                "watching_from": t.valid_from.isoformat()}
