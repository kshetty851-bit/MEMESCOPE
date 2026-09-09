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
from app.labs.rafiq import config, registry
from app.labs.rafiq.adapters import costs, evidence
from app.labs.rafiq.engine import Geometry, Mark, evaluate
from app.labs.rafiq.feed import Candidate, Observation, RafiqFeed
from app.labs.rafiq.models import (
    RafiqLabDailyState,
    RafiqLabPosition,
    RafiqLabStrategy,
)
from app.labs.rafiq.registry import LabStrategy
from app.labs.rafiq.strategies import strategy_e_ensemble as ensemble
from app.labs.rafiq.strategies.strategy_d_daily_breaker import (
    DailyState,
)
from app.labs.rafiq.strategies.strategy_d_daily_breaker import (
    evaluate as evaluate_breaker,
)

logger = get_logger(__name__)


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
            since=min(r.activated_at for r in rows))
        # One observation per token per tick, shared by all five strategies:
        # five scanners would be five different markets.
        seen: dict[str, Observation | None] = {}

        report: dict[str, dict] = {}
        for row in rows:
            spec = registry.BY_CODE[row.code]
            positions = await self._positions(row.id)
            closed = await self._settle(spec, positions, seen, now=now)
            halted, reason = await self._breaker(spec, row, positions, now=now)
            opened = 0
            if not halted:
                opened = await self._enter(spec, row, positions, candidates, seen,
                                           now=now)
            report[row.code] = {"closed": closed, "opened": opened,
                                "halted": halted, "halt_reason": reason}
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
        if verdict.halted and not state_row.halted:
            state_row.halted, state_row.halted_at = True, now
            state_row.halted_reason = verdict.reason
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
        for cand in candidates:
            if cand.mint_address in held:
                continue
            if (now - cand.detected_at).total_seconds() > config.MAX_CANDIDATE_AGE_SECONDS:
                continue
            if cand.opportunity_score < spec.profile.entry_threshold:
                continue
            obs = await self._mark(cand.mint_address, cand.token_id, seen, now=now)
            if obs is None or not obs.is_priceable:
                continue
            if (now - obs.observed_at).total_seconds() > config.STALE_GUARD_SECONDS:
                continue

            if spec.consensus_gate and not self._admitted_by_e(obs, now=now):
                continue

            stop_pct = registry.stop_pct_for(spec, obs.liquidity_usd)
            if stop_pct is None:
                continue
            notional = registry.notional_for(spec, equity=equity,
                                             liquidity_usd=obs.liquidity_usd,
                                             stop_pct=stop_pct)
            if notional <= 0 or notional > cash:
                continue
            quantity = costs.buy_quantity(notional, obs.price_usd, obs.liquidity_usd)
            if quantity is None or quantity <= 0:
                continue

            exits = spec.profile.exits
            entry_price = notional / quantity
            self._session.add(RafiqLabPosition(
                strategy_id=row.id, mint_address=cand.mint_address,
                symbol=cand.symbol, detected_at=cand.detected_at, opened_at=now,
                entry_price=entry_price, entry_observed_price=obs.price_usd,
                quantity=quantity, cost_basis=notional,
                entry_liquidity_usd=obs.liquidity_usd,
                stop_price=entry_price * (Decimal(100) - stop_pct) / 100,
                target_price=entry_price * exits.take_profit_mult,
                stop_pct=stop_pct, trailing_frac=exits.trailing_frac,
                max_hold_seconds=int(exits.max_hold.total_seconds()),
                status="open", peak_price=obs.price_usd,
                last_mark_price=obs.price_usd, last_evaluated_at=now))
            held.add(cand.mint_address)
            cash -= notional
            opened += 1
        return opened

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
