"""The tick. Reads the shared feed, writes only `rafiq_lab_*`.

WHAT ONE TICK DOES
------------------
1. activate the CURRENT run's books — config rows are selected by run id, so
   an archived book's row is never re-used or rewritten;
2. settle whatever ARCHIVED runs still hold open, under the rules frozen on
   each row, opening nothing;
3. per current book: settle its open positions against the freshest tradeable
   reading at or before now, roll the daily state, ask the breaker (and, for
   G1, move and check the equity ratchet), then consider fresh Radar
   admissions and enter the ones the book admits.

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
from app.labs.rafiq import config, entry_gate, outcomes, registry
from app.labs.rafiq.adapters import costs, evidence
from app.labs.rafiq.engine import Geometry, Mark, evaluate, off_band
from app.labs.rafiq.feed import Candidate, Observation, RafiqFeed
from app.labs.rafiq.g1 import learning
from app.labs.rafiq.g1 import strategy_G1 as g1
from app.labs.rafiq.models import (
    RafiqCandidate,
    RafiqLabAdjustment,
    RafiqLabDailyState,
    RafiqLabGateRejection,
    RafiqLabPosition,
    RafiqLabRunState,
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

#: `strategy_G1.admits` names the checks it ran; the last one is the refusal.
_G1_REFUSAL = {"liquidity": "liquidity_too_low", "market_cap": "market_cap_too_low"}

#: How many closed trades one tick feeds the learning layer. A cap, not a
#: target: the backlog after an outage drains a batch a minute, oldest first.
_LEARNING_BATCH = 200


def _dump_learning(lrn: learning.Learning, size_multiplier: float) -> dict:
    """`Learning`'s evidence as JSON. Its own fields, nothing derived."""
    return {
        "gain_threshold": str(lrn.abandon.gain_threshold),
        "abandoned": list(lrn.abandon._abandoned),
        "held": list(lrn.abandon._held),
        "regime_recent": list(lrn.regime._recent),
        "regime_baseline": lrn.regime._baseline_rate,
        "size_multiplier": size_multiplier,
    }


def _load_learning(saved: dict | None, adjustments: list) -> tuple[learning.Learning, float]:
    lrn = learning.Learning()
    if saved:
        lrn.abandon.gain_threshold = Decimal(saved["gain_threshold"])
        lrn.abandon._abandoned.extend(saved["abandoned"])
        lrn.abandon._held.extend(saved["held"])
        lrn.regime._recent.extend(saved["regime_recent"])
        lrn.regime._baseline_rate = saved["regime_baseline"]
    lrn.abandon.adjustments.extend(adjustments)
    return lrn, (saved or {}).get("size_multiplier", 1.0)


class RafiqLabService:
    """One tick's worth of work. Holds a session; writes only lab tables."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._feed = RafiqFeed(session)
        #: G1's learner per run, loaded once per tick and saved on change.
        self._learners: dict[str, tuple[learning.Learning, float]] = {}

    # --- activation ---------------------------------------------------------

    async def activate(self, *, now: datetime,
                       run: str | None = None) -> list[RafiqLabStrategy]:
        """Create one run's books once. Re-running returns what exists.

        `activated_at` never moves, so the eligibility boundary is immutable
        across restarts: an admission that predates activation is never
        entered, and backfill can therefore never look like forward trading.

        A new run is new rows at $1,000 — that is the reset. Earlier runs'
        rows are neither read nor rewritten here.
        """
        run = run or registry.CURRENT_RUN
        specs = registry.RUNS[run]
        for spec in specs:
            await self._session.execute(
                pg_insert(RafiqLabStrategy)
                .values(lab_run_id=run, code=spec.code, lane=spec.profile.lane,
                        starting_equity=config.STARTING_EQUITY,
                        profile_digest=spec.digest, activated_at=now)
                .on_conflict_do_nothing(index_elements=["lab_run_id", "code"])
            )
        await self._session.flush()
        rows = list((await self._session.execute(
            select(RafiqLabStrategy).where(RafiqLabStrategy.lab_run_id == run)
            .order_by(RafiqLabStrategy.code)
        )).scalars())

        unknown = [r.code for r in rows if r.code not in {s.code for s in specs}]
        if unknown:
            # The run holds a book this build does not define for it. Refuse:
            # those rows are somebody else's record and this code cannot
            # manage them.
            raise RuntimeError(
                f"rafiq lab run {run} holds unknown strategy codes {unknown} — "
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
        """Starting capital, minus what every entry cost, plus what every sale
        returned. Derived — never stored, so it cannot drift from the rows.

        A closed row's `exit_proceeds_usd` already includes any partial sale;
        an open row contributes the partial sales it has made so far.
        """
        spent = sum((p.cost_basis for p in positions), Decimal(0))
        back = sum((p.exit_proceeds_usd if p.exit_proceeds_usd is not None
                    else p.realised_usd for p in positions), Decimal(0))
        return row.starting_equity - spent + back

    @staticmethod
    def realised(positions) -> Decimal:
        return sum(
            ((p.exit_proceeds_usd or Decimal(0)) - p.cost_basis
             for p in positions if p.status == "closed"),
            Decimal(0),
        )

    # --- the tick -----------------------------------------------------------

    async def tick(self, *, now: datetime | None = None,
                   run: str | None = None) -> dict:
        """One pass over one run's books. Safe to run again; safe to run late.

        `run` is for tests of an archived run's mechanisms; the beat always
        trades the current run.
        """
        now = now or datetime.now(UTC)
        run = run or registry.CURRENT_RUN
        rows = await self.activate(now=now, run=run)
        candidates = await self._feed.candidates(
            since=min(r.activated_at for r in rows),
            not_before=now - timedelta(seconds=config.MAX_CANDIDATE_AGE_SECONDS))
        # One observation per token per tick, shared by every book and every
        # run: two scanners would be two different markets.
        seen: dict[str, Observation | None] = {}
        archived_closed = await self._drain(seen, run=run, now=now)
        # The learning layer hears about every trade whose post-exit hour has
        # closed BEFORE this tick decides anything, so an adjustment it makes
        # is the one the next entry uses.
        learned = (await self.learn(now=now, rows=rows))["learned"]

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
        return {"at": now.isoformat(), "run": run, "archived_closed": archived_closed,
                "learned": learned, "strategies": report}

    async def _drain(self, seen, *, run: str, now: datetime) -> int:
        """Settle what other runs still hold. Opens nothing, asks no breaker.

        A closed run is closed out under the geometry frozen on each row,
        never force-closed: selling a whole book at once is the drained-pool
        fill this lab exists to avoid. Once its last position exits it costs
        one empty query a tick.
        """
        rows = (await self._session.execute(
            select(RafiqLabPosition, RafiqLabStrategy.code)
            .join(RafiqLabStrategy, RafiqLabStrategy.id == RafiqLabPosition.strategy_id)
            .where(RafiqLabPosition.status == "open",
                   RafiqLabStrategy.lab_run_id != run)
            .order_by(RafiqLabPosition.opened_at)
        )).all()
        closed = 0
        for pos, code in rows:
            closed += await self._settle(registry.BY_CODE.get(code), [pos], seen,
                                         now=now)
        return closed

    async def _mark(self, mint: str, token_id: uuid.UUID | None,
                    seen: dict, *, now: datetime) -> Observation | None:
        if mint not in seen:
            seen[mint] = (None if token_id is None else
                          await self._feed.observe(token_id=token_id, mint=mint, at=now))
        return seen[mint]

    async def _settle(self, spec: LabStrategy | None, positions, seen, *,
                      now: datetime) -> int:
        """Evaluate every open position. Returns how many closed."""
        closed = 0
        for pos in [p for p in positions if p.status == "open"]:
            token_id = await self._feed.token_id(pos.mint_address)
            obs = await self._mark(pos.mint_address, token_id, seen, now=now)
            mark = None
            if obs is not None and obs.is_tradeable:
                mark = Mark(obs.price_usd, obs.observed_at, obs.median_price_10m)
                if off_band(mark.price, mark.median_price_10m):
                    # A glitch print is not a market: it fills nothing, and it
                    # must not become the peak a trail is measured from either.
                    continue
                if obs.price_usd > pos.peak_price:
                    pos.peak_price = obs.price_usd
                pos.last_mark_price = obs.price_usd
                pos.last_mark_liquidity_usd = obs.liquidity_usd
                pos.last_evaluated_at = now
            else:
                # The pool reads as gone, or nothing reads it: nothing to sell
                # into, so the open slice is worth nothing to the breaker until
                # the box closes it.
                pos.last_mark_liquidity_usd = Decimal(0)

            if spec is not None and spec.g1:
                closed += self._settle_g1(pos, mark, obs, now=now)
                continue

            decision = evaluate(
                Geometry(pos.entry_price, pos.stop_price, pos.target_price,
                         pos.trailing_frac, timedelta(seconds=pos.max_hold_seconds),
                         pos.opened_at),
                mark, peak_price=pos.peak_price,
                last_mark_price=pos.last_mark_price, now=now)
            if decision is None:
                continue

            # Every exit is sold into the SAME reading its price came from.
            # Never the depth at entry: that fallback sold vanished pools at
            # their entry-day depth. No tradeable reading means no depth, and
            # `sell_proceeds` values that at zero.
            closed += self._close(
                pos, fraction=pos.fraction_open, fill=decision.fill_price,
                observed=decision.observed_price,
                liquidity=obs.liquidity_usd if mark is not None else None,
                reason=decision.reason, evidence=decision.evidence, now=now)
        return closed

    def _settle_g1(self, pos: RafiqLabPosition, mark: Mark | None,
                   obs: Observation | None, *, now: datetime) -> int:
        """One G1 position, one observation, through `strategy_G1.evaluate`.

        A partial sale (`scale_out`) is booked on the row and the row stays
        open with a quarter left; every other answer sells what remains.
        """
        age = now - pos.opened_at
        if mark is None:
            # `evaluate` needs a price. Without a tradeable reading the
            # position holds — until the box, where it is worth what the pool
            # can pay for it, which is nothing.
            if age < timedelta(seconds=pos.max_hold_seconds):
                return 0
            return self._close(
                pos, fraction=pos.fraction_open, fill=Decimal(0), observed=Decimal(0),
                liquidity=None, reason=g1.Exit.MAX_HOLD, now=now,
                evidence=(f"held {age} at or past max {g1.MAX_HOLD}; no tradeable "
                          "pool reading — valued at nothing to sell into (last "
                          f"priced print {pos.last_mark_price:.10f})"))

        position = g1.Position(
            entry_price=pos.entry_price, opened_at=pos.opened_at,
            stake_usd=pos.cost_basis, fraction_open=pos.fraction_open,
            peak_price=pos.peak_price, scaled_out=pos.scaled_out,
            realised_usd=pos.realised_usd)
        abandon_gain = (g1.ABANDON_UNLESS_GAIN if pos.abandon_gain is None
                        else pos.abandon_gain)
        decision = g1.evaluate(position, mark.price, now, abandon_gain=abandon_gain)
        if decision is None:
            return 0
        _, fraction, reason = decision
        seen = (f"price {mark.price:.10f} = {mark.price / pos.entry_price:.4f}x "
                f"entry after {age}")

        if reason == g1.Exit.SCALE_OUT:
            # A level exit, so the same drift cap as every target: a gap-up
            # print is a real fill, an unlimited one is fiction.
            fill = min(mark.price, pos.entry_price * g1.SCALE_OUT_AT * config.FILL_DRIFT_CAP)
            proceeds = costs.sell_proceeds(pos.quantity * fraction, fill,
                                           obs.liquidity_usd)
            pos.scaled_out, pos.scaled_out_at, pos.scale_out_price = True, now, fill
            pos.fraction_open -= fraction
            pos.realised_usd += proceeds
            logger.info("rafiq_g1_scale_out", mint=pos.mint_address,
                        position=str(pos.id), sold=str(fraction), fill=str(fill),
                        proceeds=str(proceeds), evidence=seen)
            return 0

        if reason == g1.Exit.ABANDON:
            seen += f"; under {abandon_gain} gain at {g1.ABANDON_AFTER}"
        elif reason == g1.Exit.RUNNER_TRAIL:
            seen += f"; {g1.RUNNER_TRAIL} off the peak {pos.peak_price:.10f}"
        return self._close(pos, fraction=fraction, fill=mark.price,
                           observed=mark.price, liquidity=obs.liquidity_usd,
                           reason=reason, evidence=f"{reason}: {seen}", now=now)

    @staticmethod
    def _close(pos: RafiqLabPosition, *, fraction: Decimal, fill: Decimal,
               observed: Decimal, liquidity: Decimal | None, reason: str,
               evidence: str, now: datetime) -> int:
        """Sell what is still held into `liquidity` at `fill`, and close.

        The one exit valuation, for every book and every reason. The row's
        proceeds are the whole position's: any partial sale plus this one.
        """
        sold = pos.quantity * fraction
        pos.status = "closed"
        pos.closed_at = now
        pos.exit_price = fill
        pos.exit_observed_price = observed
        pos.exit_proceeds_usd = pos.realised_usd + costs.sell_proceeds(sold, fill, liquidity)
        pos.exit_price_impact_pct = entry_gate.impact_pct(sold * fill, liquidity)
        pos.exit_reason = reason
        pos.exit_evidence = evidence
        return 1

    # --- Strategy D's breaker ----------------------------------------------

    async def _breaker(self, spec: LabStrategy, row: RafiqLabStrategy, positions, *,
                       now: datetime) -> tuple[bool, str | None]:
        """Rafiq's own `evaluate`, over this strategy's live book.

        Runs for every current book so the page can show what the breaker
        WOULD have said; only books with `daily_breaker` are gated by it. G1
        is, and its 5% line is mark-to-market including open positions,
        valued at what they would fetch from the pool.
        """
        state_row = (await self._session.execute(
            select(RafiqLabDailyState)
            .where(RafiqLabDailyState.strategy_id == row.id)
            .order_by(RafiqLabDailyState.day.desc()).limit(1)
        )).scalars().first()

        open_values = [self._value(p) for p in positions if p.status == "open"]
        cash = self.cash(row, positions)
        equity = cash + sum(open_values, Decimal(0))
        if state_row is None or state_row.day != now.date():
            state_row = RafiqLabDailyState(
                strategy_id=row.id, lab_run_id=row.lab_run_id, day=now.date(),
                day_open_equity=equity,
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
            floor_halt, floor_reason = strategy_f2.EquityFloor(
                floor_usd=spec.equity_floor).check(equity)

        # G1's ratchet: moved by this tick's equity, then asked. Like the
        # floor it halts entries and nothing else, whatever the daily breaker
        # says.
        ratchet_halt, ratchet_reason = False, None
        if spec.g1:
            ratchet = await self._ratchet(row, equity, now=now)
            ratchet_halt, ratchet_reason = ratchet.check(equity)

        if (verdict.halted or floor_halt or ratchet_halt) and not state_row.halted:
            state_row.halted, state_row.halted_at = True, now
            state_row.halted_reason = floor_reason or ratchet_reason or verdict.reason
        # The floor binds whether or not this book is gated on the daily
        # breaker. `daily_breaker` says "consult E's loss policy"; the floor is
        # a property of the book's own capital.
        if floor_halt:
            return True, floor_reason
        if ratchet_halt:
            return True, ratchet_reason
        return (bool(verdict.halted) and spec.daily_breaker), verdict.reason

    async def _run_state(self, row: RafiqLabStrategy, *,
                         create: bool = True) -> RafiqLabRunState | None:
        """The run's persisted state, created at the ratchet's opening values
        unless `create` is off (a reader must not write)."""
        state = (await self._session.execute(
            select(RafiqLabRunState)
            .where(RafiqLabRunState.lab_run_id == row.lab_run_id)
        )).scalars().first()
        if state is None and create:
            state = RafiqLabRunState(lab_run_id=row.lab_run_id,
                                     ratchet_high_water=row.starting_equity,
                                     ratchet_floor=registry.G1_INITIAL_FLOOR)
            self._session.add(state)
            # Flushed now: sessions here run autoflush=False, and a second
            # lookup this tick would otherwise insert a duplicate.
            await self._session.flush()
        return state

    # --- G1's learning layer -------------------------------------------------

    async def _learner(self, row: RafiqLabStrategy, *,
                       create: bool = True) -> tuple[learning.Learning, float]:
        if row.lab_run_id not in self._learners:
            state = await self._run_state(row, create=create)
            made = [
                learning.Adjustment(a.at, a.parameter, a.old_value, a.new_value,
                                    a.reason, a.sample_size, float(a.z_score))
                for a in (await self._session.execute(
                    select(RafiqLabAdjustment)
                    .where(RafiqLabAdjustment.lab_run_id == row.lab_run_id,
                           RafiqLabAdjustment.parameter == "abandon_gain_threshold")
                    .order_by(RafiqLabAdjustment.at)
                )).scalars()]
            self._learners[row.lab_run_id] = _load_learning(
                state.learning if state is not None else None, made)
        return self._learners[row.lab_run_id]

    async def _save_learner(self, row: RafiqLabStrategy) -> None:
        lrn, size_multiplier = self._learners[row.lab_run_id]
        state = await self._run_state(row)
        state.learning = _dump_learning(lrn, size_multiplier)

    def _audit(self, row: RafiqLabStrategy, *, at: datetime, parameter: str,
               old, new, reason: str, sample_size: int | None = None,
               z_score: float | None = None) -> None:
        """One adjustments row and one log line for a parameter the run moved."""
        self._session.add(RafiqLabAdjustment(
            lab_run_id=row.lab_run_id, at=at, parameter=parameter,
            old_value=Decimal(str(old)), new_value=Decimal(str(new)),
            sample_size=sample_size,
            z_score=None if z_score is None else Decimal(str(z_score)),
            reason=reason))
        logger.info("rafiq_g1_parameter_moved", run=row.lab_run_id, parameter=parameter,
                    old=str(old), new=str(new), sample_size=sample_size,
                    z_score=z_score, reason=reason)

    async def learn(self, *, now: datetime, rows=None) -> dict:
        """Feed the current run's G1 books everything whose hour has closed."""
        self._learners.clear()
        if rows is None:
            rows = await self.activate(now=now)
        learned = 0
        for row in rows:
            if registry.BY_CODE[row.code].g1:
                learned += await self._learn(row, now=now)
        return {"at": now.isoformat(), "learned": learned}

    async def _learn(self, row: RafiqLabStrategy, *, now: datetime) -> int:
        """Feed `Learning.on_trade_closed` every trade whose hour has closed.

        Every exit path, oldest first, exactly once. The hour after the exit
        is read from the platform's own snapshots — which already price every
        admitted token — and written onto the row before the learner sees it.
        """
        due = list((await self._session.execute(
            select(RafiqLabPosition)
            .where(RafiqLabPosition.strategy_id == row.id,
                   RafiqLabPosition.status == "closed",
                   RafiqLabPosition.learning_recorded_at.is_(None),
                   RafiqLabPosition.closed_at <= now - outcomes.EXIT_WINDOW)
            .order_by(RafiqLabPosition.closed_at)
            .limit(_LEARNING_BATCH)
        )).scalars())
        if not due:
            return 0
        lrn, _ = await self._learner(row)
        for pos in due:
            end = pos.closed_at + outcomes.EXIT_WINDOW
            window = await self._feed.forward_window(
                mint=pos.mint_address, after=pos.closed_at, until=end)
            peak, gone = outcomes.exit_outcome(
                window, entry_price=pos.entry_price, exit_price=pos.exit_price,
                end=end, delisted_at=await self._feed.delisted_at(pos.mint_address))
            pos.forward_peak_multiple = peak
            pos.forward_went_to_zero = gone
            # "1.0 if it never recovered" — learning.py's own convention for a
            # token nothing tradeable priced again.
            made = lrn.on_trade_closed(
                exit_reason=pos.exit_reason, went_to_zero=gone,
                later_peak_multiple=1.0 if peak is None else float(peak),
                reached_take_profit=pos.scaled_out, now=now)
            pos.learning_recorded_at = now
            if made is not None:
                self._audit(row, at=made.at, parameter=made.parameter,
                            old=made.old_value, new=made.new_value, reason=made.reason,
                            sample_size=made.sample_size, z_score=made.z_score)
        await self._save_learner(row)
        return len(due)

    async def _g1_parameters(self, row: RafiqLabStrategy, *,
                             now: datetime) -> tuple[Decimal, Decimal]:
        """`Learning.current_parameters()`, read immediately before an entry
        decision: (abandon threshold for `evaluate`, size multiplier)."""
        lrn, last_multiplier = await self._learner(row)
        params = lrn.current_parameters()
        multiplier = params["size_multiplier"]
        if multiplier != last_multiplier:
            self._audit(row, at=now, parameter="size_multiplier", old=last_multiplier,
                        new=multiplier, reason=params["regime_note"],
                        sample_size=lrn.regime.sample_size)
            self._learners[row.lab_run_id] = (lrn, multiplier)
        return (Decimal(str(params["abandon_gain_threshold"])),
                Decimal(str(multiplier)))

    async def _ratchet(self, row: RafiqLabStrategy, equity: Decimal, *,
                       now: datetime) -> g1.EquityRatchet:
        """`EquityRatchet.update(equity)` against the run's persisted state.

        Called on every equity change — after settling, and before and after
        each entry — so the floor follows the high-water mark and a restart
        cannot put it back at $950. Every move is an adjustment row and a log
        line.
        """
        state = await self._run_state(row)
        ratchet = g1.EquityRatchet(high_water=state.ratchet_high_water,
                                   floor=state.ratchet_floor)
        before = ratchet.floor
        ratchet.update(equity)
        state.ratchet_high_water = ratchet.high_water
        if ratchet.floor != before:
            state.ratchet_floor = ratchet.floor
            self._audit(row, at=now, parameter="equity_ratchet_floor", old=before,
                        new=ratchet.floor,
                        reason=(f"equity ${ratchet.high_water:,.2f} is a new high-water "
                                f"mark; floor = high-water less "
                                f"{ratchet.give_back:.0%}, never down"))
        return ratchet

    @staticmethod
    def _realised_on(positions, day) -> Decimal:
        """P&L realised on `day`, each sale on the day it happened: a G1
        scale-out on the day it sold, the rest of that position on the day it
        closed. For a single-sale row that is simply proceeds less cost."""
        total = Decimal(0)
        for p in positions:
            if p.scaled_out and p.scaled_out_at and p.scaled_out_at.date() == day:
                total += p.realised_usd - p.cost_basis * (1 - p.fraction_open)
            if p.status == "closed" and p.closed_at and p.closed_at.date() == day:
                total += ((p.exit_proceeds_usd or Decimal(0)) - p.realised_usd
                          - p.cost_basis * p.fraction_open)
        return total

    @staticmethod
    def _value(pos: RafiqLabPosition) -> Decimal:
        """What the open slice would fetch from the pool as last read.

        The exit valuation, applied now: never its cost basis, and not
        `quantity x price` either. Cost-basis accounting is what let a
        dashboard here show $200.00 allocated beside a book worth $8.55, and a
        naive mark keeps a drained pool at its last price until it closes —
        the same hole, a tick later.
        """
        # The entry reading stands in for exactly one tick — between an entry
        # and its first evaluation — and on rows older than this column.
        price = pos.last_mark_price or pos.entry_price
        liquidity = (pos.entry_liquidity_usd if pos.last_mark_liquidity_usd is None
                     else pos.last_mark_liquidity_usd)
        return costs.sell_proceeds(pos.quantity * pos.fraction_open, price, liquidity)

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
            abandon_gain = size_multiplier = None

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
                    # G1's two adjustable numbers, read immediately before this
                    # decision and frozen onto the position it opens.
                    if spec.g1:
                        abandon_gain, size_multiplier = await self._g1_parameters(
                            row, now=now)
                    stop_pct, notional, verdict, reason = self._size_and_gate(
                        spec, obs, equity=equity, cash=cash,
                        size_multiplier=size_multiplier)
                    if verdict is not None and not verdict.allowed:
                        await self._count_rejection(row.id, verdict.reason, now=now)

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

            # "check() before every entry". Equity moves with every entry this
            # tick, so the ratchet is updated and asked again here rather than
            # only once before the loop.
            if spec.g1:
                ratchet = await self._ratchet(row, equity, now=now)
                ratchet_halt, why = ratchet.check(equity)
                if ratchet_halt:
                    logger.info("rafiq_g1_entries_halted", run=row.lab_run_id,
                                reason=why)
                    break

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
                    id=leg_id, lab_run_id=row.lab_run_id,
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
                    last_mark_price=obs.price_usd,
                    last_mark_liquidity_usd=obs.liquidity_usd, last_evaluated_at=now,
                    scaled_out=False, fraction_open=Decimal(1),
                    realised_usd=Decimal(0), abandon_gain=abandon_gain,
                    size_multiplier=size_multiplier))
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
            equity += costs.sell_proceeds(quantity, obs.price_usd,
                                          obs.liquidity_usd) - notional
            if remaining is not None:
                remaining -= 1
        if spec.g1:
            if opened:
                await self._ratchet(row, equity, now=now)
            if row.lab_run_id in self._learners:
                # The regime may have fixed its baseline while being asked.
                await self._save_learner(row)
        return opened

    @staticmethod
    def _size_and_gate(spec: LabStrategy, obs: Observation, *, equity: Decimal,
                       cash: Decimal, size_multiplier: Decimal | None):
        """(stop_pct, notional, verdict, reject_reason) for one candidate.

        The gate runs after sizing because it needs the notional, and after
        the cash check so a book that simply ran out of money does not record
        a gate rejection it never made. `verdict` is the gate's, when it ran.

        G1 sizes with `strategy_G1.position_size` — 1% of CURRENT equity —
        times the learning layer's multiplier, and is admitted by
        `strategy_G1.admits` before the shared impact ceiling is priced.
        """
        if spec.g1:
            stop_pct = (1 - g1.STOP_MULT) * 100
            notional = (g1.position_size(equity) * size_multiplier).quantize(
                Decimal("0.01"))
        else:
            stop_pct = registry.stop_pct_for(spec, obs.liquidity_usd)
            if stop_pct is None:
                return None, None, None, "no_stop_available"
            notional = registry.notional_for(
                spec, equity=equity, liquidity_usd=obs.liquidity_usd, stop_pct=stop_pct)
        if notional <= 0:
            return stop_pct, notional, None, "size_is_zero"
        if notional > cash:
            return stop_pct, notional, None, "insufficient_cash"
        if spec.g1:
            admitted, _, checks = g1.admits(obs.liquidity_usd, obs.market_cap)
            if not admitted:
                refusal = _G1_REFUSAL[checks[-1]] if checks else "liquidity_unknown"
                return stop_pct, notional, entry_gate.GateVerdict(False, refusal), refusal
        verdict = entry_gate.check_entry(
            liquidity_usd=obs.liquidity_usd, market_cap_usd=obs.market_cap,
            notional_usd=notional, thresholds=spec.gate)
        return stop_pct, notional, verdict, (None if verdict.allowed else verdict.reason)

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
