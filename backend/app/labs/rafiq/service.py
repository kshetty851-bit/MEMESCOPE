"""The tick. Reads the shared feed, writes only `rafiq_lab_*`.

WHAT ONE TICK DOES, PER STRATEGY
--------------------------------
1. settle open positions against the freshest observation at or before now;
2. roll the daily state and ask the breaker (D and E only);
3. consider fresh Radar admissions, and enter the ones the strategy admits.

Settling runs BEFORE entering, on purpose: the breaker's mark-to-market
equity, and the cash a new entry is sized against, must both reflect what
already happened this tick rather than what happened last tick.

**The lab never force-closes.** Strategy D halts new entries; open positions
continue to be managed by their own frozen exit rules. Panic-liquidating into
a bad market is its own risk, and D's docstring refuses to take it on.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.labs.rafiq import config, entry_gate, registry
from app.labs.rafiq.adapters import costs, evidence
from app.labs.rafiq.engine import Geometry, Mark, evaluate
from app.labs.rafiq.feed import Candidate, Observation, RafiqFeed
from app.labs.rafiq.models import (
    RafiqCandidate,
    RafiqLabDailyState,
    RafiqLabGateRejection,
    RafiqLabPosition,
    RafiqLabStrategy,
)
from app.labs.rafiq.registry import LabStrategy
from app.labs.rafiq.strategies import strategy_e_ensemble as ensemble
from app.labs.rafiq.strategies import strategy_f2
from app.labs.rafiq.strategies.strategy_d_daily_breaker import (
    DailyState,
)
from app.labs.rafiq.strategies.strategy_d_daily_breaker import (
    evaluate as evaluate_breaker,
)

logger = get_logger(__name__)

#: How far back `_filed` looks. Comfortably past the candidate window,
#: so a decision that could still be re-made is always in the set.
_FILED_LOOKBACK = timedelta(hours=6)


class RafiqLabService:
    """One tick's worth of work. Holds a session; writes only lab tables."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._feed = RafiqFeed(session)

    # --- activation ---------------------------------------------------------

    async def activate(self, *, now: datetime) -> list[RafiqLabStrategy]:
        """Create the five books once. Re-running returns what exists.

        `activated_at` never moves, so the eligibility boundary is immutable
        across restarts: an admission that predates activation is never
        entered, and backfill can therefore never look like forward trading.
        """
        for spec in registry.STRATEGIES:
            await self._session.execute(
                pg_insert(RafiqLabStrategy)
                .values(code=spec.code, lane=spec.profile.lane,
                        starting_equity=config.STARTING_EQUITY,
                        profile_digest=spec.digest, activated_at=now)
                .on_conflict_do_nothing(index_elements=["code"])
            )
        await self._session.flush()
        rows = list((await self._session.execute(
            select(RafiqLabStrategy).order_by(RafiqLabStrategy.code)
        )).scalars())

        unknown = [r.code for r in rows if r.code not in registry.BY_CODE]
        if unknown:
            # The ledger holds a book this build does not define — v1's A-E
            # under a v2 image, for instance. Refuse: the old rows are somebody
            # else's record and this code cannot manage them.
            raise RuntimeError(
                f"rafiq lab ledger holds unknown strategy codes {unknown} — "
                "archive and remove them before running this build")

        drifted = [r.code for r in rows
                   if r.profile_digest != registry.BY_CODE[r.code].digest]
        if drifted:
            # Refuse rather than trade a changed rule into a record opened
            # under the old one. The record is the asset; the code is not.
            raise RuntimeError(
                f"rafiq lab profile digest changed for {drifted} — "
                "a changed constant is a new record, not an edit")
        return rows

    # --- reading the book (nothing is stored; everything derives) -----------

    async def _positions(self, strategy_id: uuid.UUID) -> list[RafiqLabPosition]:
        return list((await self._session.execute(
            select(RafiqLabPosition)
            .where(RafiqLabPosition.strategy_id == strategy_id)
            .order_by(RafiqLabPosition.opened_at)
        )).scalars())

    @staticmethod
    def cash(row: RafiqLabStrategy, positions) -> Decimal:
        """Starting capital, minus what every entry cost, plus what every exit
        returned. Derived — never stored, so it cannot drift from the rows."""
        spent = sum((p.cost_basis for p in positions), Decimal(0))
        back = sum((p.exit_proceeds_usd or Decimal(0) for p in positions), Decimal(0))
        return row.starting_equity - spent + back

    @staticmethod
    def realised(positions) -> Decimal:
        return sum(
            ((p.exit_proceeds_usd or Decimal(0)) - p.cost_basis
             for p in positions if p.status == "closed"),
            Decimal(0),
        )

    # --- the tick -----------------------------------------------------------

    async def tick(self, *, now: datetime | None = None) -> dict:
        """One pass over every strategy. Safe to run again; safe to run late."""
        now = now or datetime.now(UTC)
        rows = await self.activate(now=now)
        candidates = await self._feed.candidates(
            since=min(r.activated_at for r in rows),
            not_before=now - timedelta(seconds=config.MAX_CANDIDATE_AGE_SECONDS))
        # One observation per token per tick, shared by all five strategies:
        # five scanners would be five different markets.
        seen: dict[str, Observation | None] = {}

        report: dict[str, dict] = {}
        for row in rows:
            spec = registry.BY_CODE[row.code]
            positions = await self._positions(row.id)
            # A retired book still settles. Its open positions run to the
            # geometry frozen on each row, because force-closing would sell
            # every one of them at once into exactly the drained pools that
            # produce the 0.0003x fills — the loss this lab exists to avoid.
            closed = await self._settle(spec, positions, seen, now=now)
            halted, reason = await self._breaker(spec, row, positions, now=now)
            opened = 0
            # `enters=False` retires a book: it keeps settling, opens nothing.
            #
            # It does NOT exist to stop books competing — they cannot. Each
            # book gets its own `positions`, its own `held` set and its own
            # cash, and `candidates` is a read-only list every book sees in
            # full. One book taking a token removes it from no other book's
            # view. An earlier version of this comment claimed otherwise and
            # was simply wrong.
            if spec.enters and not halted:
                opened = await self._enter(spec, row, positions, candidates, seen,
                                           now=now)
            report[row.code] = {"closed": closed, "opened": opened,
                                "halted": halted, "halt_reason": reason,
                                "enters": spec.enters}
        await self._session.flush()
        return {"at": now.isoformat(), "strategies": report}

    async def _mark(self, mint: str, token_id: uuid.UUID | None,
                    seen: dict, *, now: datetime) -> Observation | None:
        if mint not in seen:
            seen[mint] = (None if token_id is None else
                          await self._feed.observe(token_id=token_id, mint=mint, at=now))
        return seen[mint]

    async def _settle(self, spec: LabStrategy, positions, seen, *,
                      now: datetime) -> int:
        """Evaluate every open position. Returns how many closed."""
        closed = 0
        for pos in [p for p in positions if p.status == "open"]:
            token_id = await self._feed.token_id(pos.mint_address)
            obs = await self._mark(pos.mint_address, token_id, seen, now=now)
            mark = None
            if obs is not None and obs.is_priceable:
                mark = Mark(obs.price_usd, obs.observed_at, obs.median_price_10m)
                if obs.price_usd > pos.peak_price:
                    pos.peak_price = obs.price_usd
                pos.last_mark_price = obs.price_usd
                pos.last_evaluated_at = now

            decision = evaluate(
                Geometry(pos.entry_price, pos.stop_price, pos.target_price,
                         pos.trailing_frac, timedelta(seconds=pos.max_hold_seconds),
                         pos.opened_at),
                mark, peak_price=pos.peak_price,
                last_mark_price=pos.last_mark_price, now=now)
            if decision is None:
                continue

            # With no current observation the exit still has to be priced.
            # The pool's depth AT ENTRY is the stated assumption — it is a
            # number that was measured, unlike a zero, which is a claim that
            # nothing could be sold and is only true if someone checked.
            liquidity = (obs.liquidity_usd if obs and obs.liquidity_usd
                         else pos.entry_liquidity_usd)
            pos.status = "closed"
            pos.closed_at = now
            pos.exit_price = decision.fill_price
            pos.exit_observed_price = decision.observed_price
            pos.exit_proceeds_usd = costs.sell_proceeds(
                pos.quantity, decision.fill_price, liquidity)
            pos.exit_price_impact_pct = entry_gate.impact_pct(
                pos.quantity * decision.fill_price, liquidity)
            pos.exit_reason = decision.reason
            pos.exit_evidence = decision.evidence
            closed += 1
        return closed

    # --- Strategy D's breaker ----------------------------------------------

    async def _breaker(self, spec: LabStrategy, row: RafiqLabStrategy, positions, *,
                       now: datetime) -> tuple[bool, str | None]:
        """Rafiq's own `evaluate`, over this strategy's live book.

        Runs for every strategy so the page can show what the breaker WOULD
        have said, but only D and E are gated by the answer — that is the
        difference the two columns exist to measure.
        """
        state_row = (await self._session.execute(
            select(RafiqLabDailyState)
            .where(RafiqLabDailyState.strategy_id == row.id)
            .order_by(RafiqLabDailyState.day.desc()).limit(1)
        )).scalars().first()

        open_values = [self._value(p) for p in positions if p.status == "open"]
        cash = self.cash(row, positions)
        if state_row is None or state_row.day != now.date():
            state_row = RafiqLabDailyState(
                strategy_id=row.id, day=now.date(),
                day_open_equity=cash + sum(open_values, Decimal(0)),
                realised_today=Decimal(0), halted=False)
            self._session.add(state_row)
            await self._session.flush()

        state = DailyState(day=state_row.day,
                           day_open_equity=state_row.day_open_equity,
                           realised_today=self._realised_on(positions, state_row.day))
        verdict = evaluate_breaker(state, now=now, cash=cash,
                                   open_position_values=open_values,
                                   policy=ensemble.DAILY_POLICY)
        state_row.realised_today = state.realised_today

        # F2's hard equity floor, checked through Rafiq's own `EquityFloor` so
        # the boundary condition and the wording are his, not a re-spelling of
        # them here. It is a SEPARATE halt from the daily breaker: the breaker
        # is a loss rate inside one day and resets tomorrow, this is a level
        # the book does not come back from, and a book that has fallen through
        # it must not be restarted by a new calendar day.
        floor_halt, floor_reason = False, None
        if spec.equity_floor is not None:
            equity = cash + sum(open_values, Decimal(0))
            floor_halt, floor_reason = strategy_f2.EquityFloor(
                floor_usd=spec.equity_floor).check(equity)

        if (verdict.halted or floor_halt) and not state_row.halted:
            state_row.halted, state_row.halted_at = True, now
            state_row.halted_reason = floor_reason or verdict.reason
        # The floor binds whether or not this book is gated on the daily
        # breaker. `daily_breaker` says "consult E's loss policy"; the floor is
        # a property of the book's own capital.
        if floor_halt:
            return True, floor_reason
        return (bool(verdict.halted) and spec.daily_breaker), verdict.reason

    @staticmethod
    def _realised_on(positions, day) -> Decimal:
        return sum(
            ((p.exit_proceeds_usd or Decimal(0)) - p.cost_basis for p in positions
             if p.status == "closed" and p.closed_at and p.closed_at.date() == day),
            Decimal(0),
        )

    @staticmethod
    def _value(pos: RafiqLabPosition) -> Decimal:
        """A position's CURRENT mark, never its cost basis.

        Cost-basis accounting is exactly what let a dashboard here show
        $200.00 allocated beside a book actually worth $8.55, and a breaker
        built on it would never see the hole.
        """
        # `entry_price` is the fallback for exactly one tick — between an
        # entry and its first evaluation — and never after.
        return pos.quantity * (pos.last_mark_price or pos.entry_price)

    # --- entries ------------------------------------------------------------

    async def _enter(self, spec: LabStrategy, row: RafiqLabStrategy, positions,
                     candidates: list[Candidate], seen, *, now: datetime) -> int:
        held = {p.mint_address for p in positions}
        cash = self.cash(row, positions)
        equity = cash + sum((self._value(p) for p in positions
                             if p.status == "open"), Decimal(0))
        opened = 0
        # Which mints this book has already filed a decision on. Loaded once
        # per tick so a candidate the gate refuses on every tick for an hour
        # costs one row and one feature read, not 3,600 of each.
        filed = await self._filed(row.id, now=now)

        # Rafiq's `MAX_TRADES_PER_DAY`, counted against what was actually
        # opened today rather than an in-process counter: a worker restart
        # would reset the counter and the cap would silently stop binding.
        # Distinct mints, so a book that splits into legs is not charged twice
        # for one decision.
        remaining = None
        if spec.max_trades_per_day is not None:
            today = len({p.mint_address for p in positions
                         if p.opened_at.date() == now.date()})
            remaining = spec.max_trades_per_day - today

        for cand in candidates:
            if cand.mint_address in held:
                continue

            # Every `continue` below is a decision, and a decision nobody
            # recorded is the reason `FINDINGS.md` cannot evaluate a filter:
            # "we never looked at it" and "we looked and the pool was thin"
            # are different rejections and both have to be on disk.
            obs: Observation | None = None
            stop_pct = notional = None
            verdict = None
            reason: str | None = None

            if (now - cand.detected_at).total_seconds() > config.MAX_CANDIDATE_AGE_SECONDS:
                reason = "candidate_too_old"
            elif cand.opportunity_score < spec.profile.entry_threshold:
                reason = "score_below_threshold"
            else:
                obs = await self._mark(cand.mint_address, cand.token_id, seen, now=now)
                if obs is None:
                    reason = "no_observation"
                elif not obs.is_priceable:
                    reason = "not_priceable"
                elif (now - obs.observed_at).total_seconds() > config.STALE_GUARD_SECONDS:
                    reason = "observation_stale"
                elif spec.consensus_gate and not self._admitted_by_e(obs, now=now):
                    reason = "consensus_refused"
                else:
                    stop_pct = registry.stop_pct_for(spec, obs.liquidity_usd)
                    if stop_pct is None:
                        reason = "no_stop_available"
                    else:
                        notional = registry.notional_for(
                            spec, equity=equity, liquidity_usd=obs.liquidity_usd,
                            stop_pct=stop_pct)
                        if notional <= 0:
                            reason = "size_is_zero"
                        elif notional > cash:
                            reason = "insufficient_cash"
                        else:
                            verdict = entry_gate.check_entry(
                                liquidity_usd=obs.liquidity_usd,
                                market_cap_usd=obs.market_cap,
                                notional_usd=notional, thresholds=spec.gate)
                            if not verdict.allowed:
                                reason = verdict.reason
                                await self._count_rejection(row.id, verdict.reason,
                                                            now=now)

            if reason is not None:
                # First rejection wins: its feature snapshot is the one the
                # forward window is measured from.
                if cand.mint_address not in filed:
                    await self._file(spec, row, cand, obs, now=now,
                                     reason=reason, notional=notional,
                                     stop_pct=stop_pct, verdict=verdict)
                    filed.add(cand.mint_address)
                continue

            # THE v2 ENTRY GATE ran above, priced on the WHOLE position before
            # anything is bought — C2 splitting into two halves must not buy it
            # an easier gate than A2 gets, or the books stop being comparable
            # on the one rule they are supposed to share. It runs after sizing
            # because it needs the notional, and after the cash check so that a
            # book which simply ran out of money does not record a gate
            # rejection it never actually made.
            quantity = costs.buy_quantity(notional, obs.price_usd, obs.liquidity_usd)
            if quantity is None or quantity <= 0:
                if cand.mint_address not in filed:
                    await self._file(spec, row, cand, obs, now=now,
                                     reason="unquantifiable", notional=notional,
                                     stop_pct=stop_pct, verdict=verdict)
                    filed.add(cand.mint_address)
                continue

            # The daily cap is checked LAST, on purpose. Checked first it
            # would be the recorded reason for nearly the whole stream — the
            # cap is 20 and the Radar admits about 605 a day — and every one
            # of those rows would lose the reason it would actually have
            # failed for. Checked here it marks exactly the candidates the cap
            # cost the book: ones that passed every other condition. That is
            # the number worth having, and it leaves the rest of the
            # population readable.
            if remaining is not None and remaining <= 0:
                if cand.mint_address not in filed:
                    await self._file(spec, row, cand, obs, now=now,
                                     reason="daily_trade_cap", notional=notional,
                                     stop_pct=stop_pct, verdict=verdict)
                    filed.add(cand.mint_address)
                continue

            # Read AFTER the decision is settled and BEFORE the row exists, so
            # the reading is the one the decision was made under and cannot be
            # mistaken for a later state of the store. It cannot change the
            # outcome: every gate above has already passed, this issues two
            # SELECTs against tables the platform fills on its own schedule,
            # and a silent store returns a named absence rather than raising.
            features = await self._feed.entry_features(mint=cand.mint_address,
                                                       at=now)

            # One buy, then split. Sizing each leg separately would have this
            # book pay two small impacts instead of the one large one it really
            # pays, which is a cost advantage the experiment never granted it.
            exits = spec.profile.exits
            entry_price = notional / quantity
            # Ids assigned here rather than by the server default, so leg 1's
            # id is known before the row is flushed and the candidate row can
            # name it without reading anything back.
            leg_ids = [uuid.uuid4() for _ in spec.legs]
            for index, (leg, leg_id) in enumerate(
                    zip(spec.legs, leg_ids, strict=True), start=1):
                self._session.add(RafiqLabPosition(
                    id=leg_id,
                    strategy_id=row.id, mint_address=cand.mint_address,
                    symbol=cand.symbol, detected_at=cand.detected_at, opened_at=now,
                    leg=index,
                    entry_price=entry_price, entry_observed_price=obs.price_usd,
                    quantity=quantity * leg.fraction,
                    cost_basis=notional * leg.fraction,
                    entry_liquidity_usd=obs.liquidity_usd,
                    entry_market_cap_usd=obs.market_cap,
                    entry_price_impact_pct=verdict.entry_impact_pct,
                    entry_top10_holder_pct=features.top10_holder_pct,
                    entry_top10_captured_at=features.top10_captured_at,
                    entry_lp_status=features.lp_status,
                    entry_lp_reason_codes=features.lp_reason_codes,
                    entry_lp_checked_at=features.lp_checked_at,
                    entry_features_error=features.error,
                    stop_price=entry_price * (Decimal(100) - stop_pct) / 100,
                    target_price=(None if leg.take_profit_mult is None
                                  else entry_price * leg.take_profit_mult),
                    stop_pct=stop_pct, trailing_frac=leg.trailing_frac,
                    max_hold_seconds=int(exits.max_hold.total_seconds()),
                    status="open", peak_price=obs.price_usd,
                    last_mark_price=obs.price_usd, last_evaluated_at=now))
                opened += 1
            # Flushed before the candidate row is written, because that row
            # carries a foreign key to leg 1 and `_file` issues a Core INSERT
            # that does not wait for the session's pending adds.
            await self._session.flush()
            # An entry supersedes any earlier rejection of the same mint: one
            # decision matters and it is this one.
            await self._file(spec, row, cand, obs, now=now, reason=None,
                             notional=notional, stop_pct=stop_pct,
                             verdict=verdict, features=features,
                             position_id=leg_ids[0])
            filed.add(cand.mint_address)
            held.add(cand.mint_address)
            cash -= notional
            if remaining is not None:
                remaining -= 1
        return opened

    async def _filed(self, strategy_id: uuid.UUID, *, now: datetime) -> set[str]:
        """Mints this book filed a decision on recently.

        Bounded rather than "ever": a candidate has to be under
        `MAX_CANDIDATE_AGE_SECONDS` old to be considered at all, so a decision
        from a day ago cannot be re-made and does not need to be in this set.
        Without the bound this query grows without limit and is issued on every
        tick. The set is only an optimisation — the `ON CONFLICT` rule in
        `_file` is what actually guarantees one row per candidate, so a mint
        that falls outside the window costs at most one insert that does
        nothing.
        """
        return set((await self._session.execute(
            select(RafiqCandidate.mint_address)
            .where(RafiqCandidate.strategy_id == strategy_id,
                   RafiqCandidate.decided_at >= now - _FILED_LOOKBACK)
        )).scalars())

    async def _file(self, spec: LabStrategy, row: RafiqLabStrategy,
                    cand: Candidate, obs: Observation | None, *, now: datetime,
                    reason: str | None, notional: Decimal | None,
                    stop_pct: Decimal | None, verdict=None, features=None,
                    position_id: uuid.UUID | None = None) -> None:
        """Record one decision — entered or refused — with its features.

        The features are read here for a rejection and passed in for an entry,
        because the entry already read them for the position row and reading
        them twice could return two different answers for one decision.

        `ON CONFLICT DO UPDATE` is guarded on the stored outcome, so an entry
        can overwrite an earlier rejection of the same mint and a later
        rejection can never overwrite anything. The caller's `filed` set
        already skips repeated rejections; this makes the rule hold even if
        two ticks run concurrently.
        """
        if features is None:
            features = await self._feed.entry_features(mint=cand.mint_address,
                                                        at=now)
        values = {
            "strategy_id": row.id,
            "mint_address": cand.mint_address,
            "symbol": cand.symbol,
            "detected_at": cand.detected_at,
            "decided_at": now,
            "outcome": "rejected" if reason else "entered",
            "reject_reason": reason,
            "position_id": position_id,
            "observed_at": obs.observed_at if obs else None,
            "price_usd": obs.price_usd if obs else None,
            "liquidity_usd": obs.liquidity_usd if obs else None,
            "market_cap_usd": obs.market_cap if obs else None,
            "volume_m5": obs.volume_m5 if obs else None,
            "liquidity_change_15m": obs.liquidity_change_15m if obs else None,
            "opportunity_score": cand.opportunity_score,
            "flow": ({"buyers": obs.buyers, "sellers": obs.sellers,
                      "buys": obs.buys, "sells": obs.sells,
                      "top10_tx_share": (None if obs.top10_tx_share is None
                                         else str(obs.top10_tx_share))}
                     if obs is not None else None),
            "notional_usd": notional,
            "stop_pct": stop_pct,
            "entry_impact_pct": verdict.entry_impact_pct if verdict else None,
            "safety_status": (obs.safety.value if obs and obs.safety else None),
            "safety_observed_at": obs.safety_observed_at if obs else None,
            "top10_holder_pct": features.top10_holder_pct,
            "top10_captured_at": features.top10_captured_at,
            "lp_status": features.lp_status,
            "lp_reason_codes": features.lp_reason_codes,
            "lp_checked_at": features.lp_checked_at,
            "features_error": features.error,
        }
        stmt = pg_insert(RafiqCandidate).values(**values)
        await self._session.execute(stmt.on_conflict_do_update(
            constraint="uq_rafiq_lab_candidates_strategy_mint",
            set_={k: v for k, v in values.items()
                  if k not in ("strategy_id", "mint_address")},
            # Only an entry may overwrite, and only a rejection may be
            # overwritten. Both halves are needed: the first stops a stored
            # entry being replaced, the second stops a later rejection
            # replacing an earlier one whose forward window has already
            # started being measured.
            where=(RafiqCandidate.outcome != "entered")
                  & (stmt.excluded.outcome == "entered"),
        ))

    async def _count_rejection(self, strategy_id: uuid.UUID, reason: str, *,
                               now: datetime) -> None:
        """Increment one book's counter for one gate reason.

        A counter, not a row per rejection: the gate refuses most of the stream
        on most ticks, and a row each would be a table nobody could read. What
        a read-out needs is the rate and the breakdown, which is what this is.
        """
        await self._session.execute(
            pg_insert(RafiqLabGateRejection)
            .values(strategy_id=strategy_id, reason=reason, rejections=1,
                    last_at=now)
            .on_conflict_do_update(
                index_elements=["strategy_id", "reason"],
                set_={"rejections": RafiqLabGateRejection.rejections + 1,
                      "last_at": now})
        )

    @staticmethod
    def _admitted_by_e(obs: Observation, *, now: datetime) -> bool:
        """Rafiq's own `evaluate_entry`, over streams the feed can supply.

        The social stream is never constructed — the platform has no social
        data — so E must find its two confirming streams among on-chain, DEX
        and safety, with safety mandatory. That is a real constraint on how
        often E can trade, and it is the honest one.
        """
        streams = evidence.from_feed(obs, safety=obs.safety,
                                     safety_observed_at=obs.safety_observed_at)
        return ensemble.evaluate_entry(
            streams, buyers=obs.buyers, sellers=obs.sellers, buys=obs.buys,
            sells=obs.sells, volume_m5=obs.volume_m5, market_cap=obs.market_cap,
            liquidity=obs.liquidity_usd, now=now).admitted
