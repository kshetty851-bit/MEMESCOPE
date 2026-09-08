"""Mirror one wallet's trades into a $100 paper book — forward only.

## The watermark, which is the rule that matters

**Nothing the leader did before this lab started is ever actionable.** His
recent history is always in view — the follower returns his last hundred swaps,
which can span days — so without a hard cutoff the first tick would open the
whole book on trades that are already over. Every signal older than the
tournament's `valid_from` is recorded and refused with `before_watch_start`.

A second cutoff sits behind it: `MAX_SIGNAL_AGE_SECONDS`. He holds a median of
8.5 minutes, so copying a trade even an hour old is not copying that trade — it
is opening a fresh position at a price his own buying already moved.

## Recorded, then decided

Every leader trade gets a row whether or not we act, because the refusals are
the evidence. "We copied 40 of his 300 trades" is the finding; a ledger of only
our own fills cannot produce it. `signature` is UNIQUE in the database rather
than checked here, because two ticks can read before either writes.

## Sizing is ours

His median buy is ~$106 against our $100 book. We mirror WHICH token and WHEN,
never how much: a fixed $20, at most five open.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.logging import get_logger
from app.lab import execution
from app.lab.service import LabService
from app.models.lab import (
    LabDecision,
    LabPosition,
    LabStrategy,
    LabTournament,
)
from app.models.market import (
    LANE_DISPLAY,
    TokenEnrichmentState,
    TokenMarketSnapshot,
    TradingStatus,
)
from app.models.pumpfun import PumpfunSignal
from app.pumpfun import spec
from app.pumpfun.follower import LeaderTrade, recent_trades
from app.repositories.token import TokenRepository
from app.services.market.providers.base import MarketDataProvider
from app.services.market.providers.registry import get_provider
from app.services.market.service import MarketEnrichmentService

logger = get_logger(__name__)

EXIT_REASON = "leader_sold"

#: Provenance marker for a mint this lab registered because the leader traded
#: it. Deliberately NOT the pump.fun program id: `_is_pumpfun`, the Universe
#: rules and the real-wallet safety gate all read `source_program`, and writing
#: a program id we did not observe would be claiming a discovery that never
#: happened. Follows the `jupiter_verified` precedent in `app/universe`.
SOURCE_PROGRAM = "pumpfun_copy"


class PumpfunService:
    def __init__(self, session, *, provider: MarketDataProvider | None = None) -> None:
        self._session = session
        self._lab = LabService(session, registry=spec)
        self._provider = provider
        self._owns_provider = False

    async def _row(self) -> tuple[LabTournament, LabStrategy] | None:
        t = (await self._session.execute(
            select(LabTournament).where(
                LabTournament.spec_version == spec.SPEC_VERSION)
        )).scalars().first()
        if t is None:
            return None
        row = (await self._session.execute(
            select(LabStrategy).where(LabStrategy.tournament_id == t.id)
        )).scalars().first()
        return None if row is None else (t, row)

    async def _seen(self, signature: str) -> bool:
        return (await self._session.execute(
            select(PumpfunSignal.id).where(PumpfunSignal.signature == signature)
        )).scalars().first() is not None

    async def _mark_price(self, mint: str, now: datetime):
        """Latest tradeable print for a mint, or None.

        Deliberately strict: a token we cannot price is one we refuse to buy.
        The leader trades many names our scanner has never seen — only 10% of
        his month had five or more snapshots here — and inventing an entry
        price for the rest would make the whole book fiction.
        """
        snap = (await self._session.execute(
            select(TokenMarketSnapshot)
            .where(TokenMarketSnapshot.mint_address == mint,
                   TokenMarketSnapshot.trading_status == TradingStatus.TRADING,
                   TokenMarketSnapshot.price_usd.isnot(None),
                   TokenMarketSnapshot.suspect.is_(False))
            .order_by(TokenMarketSnapshot.captured_at.desc()).limit(1)
        )).scalars().first()
        if snap is None or not snap.price_usd or not snap.liquidity_usd:
            return None
        age = (now - snap.captured_at).total_seconds()
        if age > execution.STALE_GUARD_SECONDS:
            return None
        return snap

    async def _market(self) -> MarketDataProvider:
        """The provider for this tick, started once and closed by `tick`.

        ponytail: one instance per tick, so its circuit breaker is per tick
        too. That is fine at this volume — he trades a handful of times a
        minute and most of those need no call at all — but a lab that fetched
        far more would want the worker's long-lived provider passed in, which
        is why the constructor accepts one.
        """
        if self._provider is None:
            self._provider = get_provider()
            self._owns_provider = True
            await self._provider.start()
        return self._provider

    async def _enrol(
        self, trade: LeaderTrade, now: datetime
    ) -> tuple[MarketEnrichmentService, TokenEnrichmentState] | None:
        """Register a mint we cannot price, so the pipeline can price it.

        The scanner subscribes to pump.fun's bonding curve; the leader trades
        wherever he likes, so most of his names have no `discovered_tokens` row
        at all and therefore no enrichment state, no snapshots and no price.
        There is nothing wrong with those tokens — we simply never looked.

        Registration is shallow, exactly as `app/universe/enrolment.py` does
        it: a token row and an enrichment state, nothing else. No Radar
        admission, no Track Record entry. It is a thing to observe because
        somebody we are watching touched it, not an opportunity anyone
        detected.

        The provenance is HIS transaction — a real signature at a real slot —
        rather than the synthetic pair the Universe has to invent, because
        unlike a vendor list a swap genuinely is a chain observation.
        """
        tokens = TokenRepository(self._session)
        token = await tokens.get_by_mint(trade.mint)
        if token is None:
            token = await tokens.insert_if_absent({
                "mint_address": trade.mint,
                "signature": trade.signature,
                "slot": trade.slot,
                "discovered_at": now,
                "block_time": trade.at,
                "source_program": SOURCE_PROGRAM,
            })
            if token is None:                     # lost the race; it exists now
                token = await tokens.get_by_mint(trade.mint)
            if token is None:
                return None
            logger.info("pumpfun_token_enrolled", mint=trade.mint,
                        signature=trade.signature)

        enrichment = MarketEnrichmentService(self._session, await self._market())
        state = await enrichment.states.ensure_state(
            token_id=token.id, mint_address=token.mint_address,
            next_refresh_at=now,
            # Straight into the display lane. A nursery token can be trimmed by
            # the membership beat, and a mint we are about to hold must not be:
            # HQ INC-056 was 61 of 108 Lab positions frozen unpriceable because
            # their tokens fell out of the refresh rotation. Once a position is
            # actually open `priority.resolve_membership` keeps it here on its
            # own — this only covers the gap before that beat runs.
            priority=LANE_DISPLAY,
        )
        if state is None:
            state = await enrichment.states.get_by_mint(trade.mint)
        if state is None:
            return None
        return enrichment, state

    async def _price_now(
        self, trade: LeaderTrade, now: datetime
    ) -> TokenMarketSnapshot | str:
        """Quote a mint on demand — or say precisely why we could not.

        `enrich` and not a bare provider call: it is the one place that writes
        a snapshot, and it carries the data-quality firewall with it — the
        suspect annotation `_mark_price` filters on, the dead-letter
        accounting, the refresh schedule. A private write here would produce a
        row the rest of the platform does not trust and cannot audit.

        Returns the snapshot, or the REFUSAL that explains its absence. Three
        different facts used to arrive here as the single word `unpriceable`,
        and they answer opposite questions:

          * `no_market` — the provider answered and this mint has no indexed
            pool. A fact about the token, and the interesting one: he holds a
            median of 8.5 minutes and freshly launched mints are routinely
            unindexed for their first minutes, so this is where "copying him is
            structurally impossible" would show up.
          * `quote_unavailable` — the provider errored, or the breaker was open
            and it was never asked. **Not evidence about the token at all.**
            Conflating a DexScreener outage with "this coin has no market"
            would turn our bad afternoon into a finding about his strategy.
          * `unpriceable` — a print exists but may not be acted on: suspect,
            stale, off the glitch band, or not trading.

        `without_market` is read BEFORE `snapshots_written` because they are
        not exclusive: the dead-letter path writes an INACTIVE snapshot for a
        token it has just counted as having no market.
        """
        found = await self._enrol(trade, now)
        if found is None:
            return "enrol_failed"
        enrichment, state = found
        outcome = await enrichment.enrich([state])
        if outcome.deferred or outcome.failed:
            logger.warning("pumpfun_quote_unavailable", mint=trade.mint,
                           deferred=outcome.deferred, failed=outcome.failed)
            return "quote_unavailable"
        if outcome.without_market:
            return "no_market"
        if outcome.snapshots_written == 0:
            return "quote_unavailable"
        snap = await self._mark_price(trade.mint, now)
        return snap if snap is not None else "unpriceable"

    async def _record(self, t, trade: LeaderTrade, outcome: str, *,
                      acted: bool = False, position_id=None,
                      now: datetime) -> None:
        self._session.add(PumpfunSignal(
            tournament_id=t.id, signature=trade.signature,
            mint_address=trade.mint, side=trade.side,
            leader_sol=(Decimal(str(round(trade.sol_amount, 4)))
                        if trade.sol_amount is not None else None),
            leader_at=trade.at, seen_at=now,
            acted=acted, outcome=outcome, position_id=position_id,
        ))
        try:
            await self._session.flush()
        except IntegrityError:
            # Another tick recorded this signature first. That is the unique
            # constraint doing its job, not an error.
            await self._session.rollback()

    async def _open(self, t, row, trade: LeaderTrade, now: datetime) -> str:
        s = spec.BY_ID[row.strategy_id]
        held = (await self._session.execute(
            select(LabPosition).where(LabPosition.strategy_row_id == row.id,
                                      LabPosition.status == "open")
        )).scalars().all()
        mine = next((p for p in held if p.mint_address == trade.mint), None)

        # Units, not positions. `uq_lab_position_once` allows one row per
        # (strategy, mint) for the life of the tournament — an invariant every
        # other lab depends on — so a scale-in adds to the row we already hold
        # rather than opening a second one beside it.
        units_open = sum(self._units_held(p, s.size_usd) for p in held)
        if units_open >= s.max_concurrent:
            return "max_concurrent"
        if row.cash < s.size_usd:
            return "insufficient_cash"
        if mine is not None:
            if self._units_held(mine, s.size_usd) >= spec.MAX_UNITS_PER_MINT:
                return "max_units_per_mint"
            return await self._add(t, row, mine, trade, now)
        snap = await self._mark_price(trade.mint, now)
        on_demand = snap is None
        if snap is None:
            # He trades names the scanner never subscribed to. Refusing them is
            # not measuring his strategy, it is measuring our coverage of it —
            # so ask the provider now instead of declining on our own ignorance.
            got = await self._price_now(trade, now)
            if isinstance(got, str):
                return got
            snap = got
        qty = execution.buy_quantity(s.size_usd, snap.price_usd, snap.liquidity_usd)
        if qty is None or qty <= 0:
            return "unpriceable"

        # Every Lab position descends from a decision, and this one is no
        # exception — `lab_positions.decision_id` is NOT NULL and that
        # invariant is worth satisfying rather than relaxing. The decision here
        # is his: the checkpoint is the moment he traded, and the features
        # record WHOSE trade and WHICH transaction, so a position can always be
        # traced back to the signature that caused it.
        decision = LabDecision(
            strategy_row_id=row.id, strategy_id=row.strategy_id,
            mint_address=trade.mint, token_id=snap.token_id,
            checkpoint_at=trade.at, checkpoint_minutes=0,
            decided_at=now, eligible=True,
            features={"leader": spec.LEADER_ADDRESS,
                      "leader_label": spec.LEADER_LABEL,
                      "signature": trade.signature,
                      "leader_sol": (round(trade.sol_amount, 4)
                                    if trade.sol_amount is not None else None),
                      "lag_seconds": round((now - trade.at).total_seconds(), 1),
                      # Whether this fill existed only because we went and
                      # fetched a price. The v1.0.0 book could not have opened
                      # it, so the two runs stay comparable.
                      "priced_on_demand": on_demand},
            requested_size_usd=s.size_usd,
        )
        self._session.add(decision)
        await self._session.flush()

        row.cash -= s.size_usd
        pos = LabPosition(
            decision_id=decision.id,
            strategy_row_id=row.id, strategy_id=row.strategy_id,
            mint_address=trade.mint, token_id=snap.token_id,
            opened_at=now, entry_price=snap.price_usd,
            entry_liquidity_usd=snap.liquidity_usd, size_usd=s.size_usd,
            quantity=qty, quantity_remaining=qty,
            banked_proceeds_usd=Decimal(0), status="open",
            peak_exec_multiple=Decimal(1), last_exec_multiple=Decimal(1),
            last_open_value_usd=s.size_usd, entry_source="pumpfun_copy",
        )
        self._session.add(pos)
        await self._session.flush()
        await self._record(t, trade, "opened", acted=True, position_id=pos.id,
                           now=now)
        return "opened"

    @staticmethod
    def _units_held(pos: LabPosition, unit: Decimal) -> int:
        """Units still deployed in this position.

        NOT `size_usd / unit`: that is what was BOUGHT. `size_usd` and
        `quantity` are the original cost and the original quantity, immutable
        once a unit is added, because `settle` defines the executable multiple
        as `sell_proceeds(quantity) / size_usd` — the V6 frozen definition of a
        2x. Decrementing them on a trim would inflate the multiple of every
        position we scale out of. What a trim moves is `quantity_remaining`,
        exactly as the registry's own PARTIAL exit does, so the units still at
        risk are the bought units scaled by the fraction still held.
        """
        if not pos.quantity or pos.quantity <= 0:
            return 0
        bought = pos.size_usd / unit
        return int((bought * (pos.quantity_remaining / pos.quantity))
                   .quantize(Decimal(1), rounding=ROUND_HALF_UP))

    async def _add(self, t, row, pos: LabPosition, trade: LeaderTrade,
                   now: datetime) -> str:
        """He bought a name we already hold. Add one unit to it.

        The position averages: stake, quantity and entry price all move to the
        blended figures, which is what makes `exec_multiple` — proceeds over
        cost — stay meaningful across the adds. `peak_exec_multiple` is left
        alone; it is only read by a trailing stop, and this registry declares
        none, so rebasing it would be inventing a number nothing consumes.

        `entry_liquidity_usd` keeps the FIRST entry's reading on purpose: it
        records the conditions we entered under, and the liquidity exits that
        would read it are not enabled here either.

        No new `LabDecision`. A position has exactly one, and the ledger of
        every leader trade — signature, side, position — is `pumpfun_signals`,
        which is where the audit trail for an add already lives.
        """
        s = spec.BY_ID[row.strategy_id]
        snap = await self._mark_price(trade.mint, now)
        if snap is None:
            got = await self._price_now(trade, now)
            if isinstance(got, str):
                return got
            snap = got
        qty = execution.buy_quantity(s.size_usd, snap.price_usd, snap.liquidity_usd)
        if qty is None or qty <= 0:
            return "unpriceable"

        row.cash -= s.size_usd
        pos.size_usd += s.size_usd
        pos.quantity += qty
        pos.quantity_remaining += qty
        pos.entry_price = pos.size_usd / pos.quantity
        await self._session.flush()
        await self._record(t, trade, "added", acted=True, position_id=pos.id,
                           now=now)
        return "added"

    async def _close(self, t, row, trade: LeaderTrade, now: datetime) -> str:
        """He sold. Release ONE unit of what we hold in that name.

        v1.1.0 closed the whole position on his first sell, which exited while
        he was still holding — he sells in ~1.9 tranches a name — and that
        biases the record against the position that runs, the only outcome this
        experiment is trying to catch.

        The last unit closes the position; every earlier one trims it. The
        fraction is of `quantity_remaining` rather than of the original stake,
        so successive trims release successive units rather than shrinking
        geometrically toward never selling out.
        """
        s = spec.BY_ID[row.strategy_id]
        pos = (await self._session.execute(
            select(LabPosition).where(LabPosition.strategy_row_id == row.id,
                                      LabPosition.mint_address == trade.mint,
                                      LabPosition.status == "open")
        )).scalars().first()
        if pos is None:
            return "not_held"

        units = max(1, self._units_held(pos, s.size_usd))
        if units > 1:
            # 1/units of what REMAINS, so each trim releases the same slice of
            # the original: with four units it is Q/4, then (3Q/4)/3, then
            # (Q/2)/2 — never a geometric decay that would leave a tail nobody
            # ever sells.
            out = await self._lab.trim_manually(
                position_id=pos.id, now=now, actor="pumpfun_copy",
                fraction=Decimal(1) / Decimal(units),
            )
            if not out.get("trimmed"):
                return out.get("reason", "trim_refused")
            await self._record(t, trade, "trimmed", acted=True,
                               position_id=pos.id, now=now)
            return "trimmed"

        out = await self._lab.close_manually(
            position_id=pos.id, now=now, actor="pumpfun_copy",
            reason=EXIT_REASON,
        )
        if not out.get("closed"):
            return out.get("reason", "close_refused")
        await self._record(t, trade, "closed", acted=True, position_id=pos.id,
                           now=now)
        return "closed"

    async def tick(self, *, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(UTC)
        t = await self._lab.activate(valid_from=now)
        found = await self._row()
        if found is None:
            return {"skipped": "not_activated"}
        _t, row = found

        trades = await recent_trades()
        counts: dict[str, int] = {}
        try:
            # Oldest first: his own sequence is the one we replay, and a buy that
            # arrives after its own sell would leave the book holding a position he
            # has already exited.
            for trade in sorted(trades, key=lambda x: x.at):
                if await self._seen(trade.signature):
                    continue
                if trade.at < t.valid_from:
                    outcome = "before_watch_start"
                elif (now - trade.at).total_seconds() > spec.MAX_SIGNAL_AGE_SECONDS:
                    outcome = "stale_signal"
                elif trade.side == "buy":
                    outcome = await self._open(t, row, trade, now)
                else:
                    outcome = await self._close(t, row, trade, now)
                if outcome not in ("opened", "added", "trimmed", "closed"):
                    await self._record(t, trade, outcome, now=now)
                counts[outcome] = counts.get(outcome, 0) + 1
        finally:
            if self._owns_provider and self._provider is not None:
                await self._provider.close()
                self._provider = None
                self._owns_provider = False

        settled = await self._lab.settle(now=now)
        await self._lab.record_equity(now=now)
        equity = await self._lab.equity(row)
        if counts.get("opened") or counts.get("closed"):
            logger.info("pumpfun_tick", **counts, equity=str(equity))
        return {"signals": counts, "settled": settled, "equity": str(equity),
                "watching_from": t.valid_from.isoformat()}
