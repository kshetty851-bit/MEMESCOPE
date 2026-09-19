"""The tick: six books, one engine. Writes only `rafiqv2_*`.

The shared token feed is read through the Rafiq Lab's `RafiqFeed`, which is
read-only by test, together with that lab's cost model, entry gate, glitch
guard and daily breaker. One implementation of each, not a second copy.

ONE TICK, PER BOOK
------------------
1. settle open positions against this tick's reading; every close goes into
   the death-rate window as it happens;
2. hand the learner (`on_exit`) every closed trade whose hour after exit has
   closed, with the best price it reached in that hour;
3. value the book at what its pools would pay, move the ratchet, roll the day
   and ask the daily breaker;
4. unless a breaker holds entries: per fresh Radar admission, read
   `current_parameters()`, size, gate, buy, and `on_entry()` the buy.

Settle before enter, so the breakers and the next entry's size see what this
tick already closed. Nothing is ever force-closed: a halt stops entries only.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.labs.rafiq import entry_gate, outcomes
from app.labs.rafiq.adapters import costs
from app.labs.rafiq.config import MAX_CANDIDATE_AGE_SECONDS, STALE_GUARD_SECONDS
from app.labs.rafiq.engine import off_band
from app.labs.rafiq.feed import Candidate, Observation, RafiqFeed, tradeable
from app.labs.rafiq.strategies.strategy_d_daily_breaker import DailyState
from app.labs.rafiq.strategies.strategy_d_daily_breaker import evaluate as daily_verdict
from app.labs.rafiqv2 import config, engine, learning
from app.labs.rafiqv2.config import Book
from app.labs.rafiqv2.models import Rafiqv2Adjustment, Rafiqv2Book, Rafiqv2Position
from app.labs.rafiqv2.strategy_common import DeathRateBreaker, EquityRatchet, ProfitLock

logger = get_logger(__name__)

#: One tick at a time across every worker: the beat is 30s and a slow tick
#: must not overlap the next. Transaction-scoped, so a crash releases it.
_TICK_LOCK = 0x52414649513256  # "RAFIQ2V"

#: Closed trades one tick hands the learner, oldest first. A cap, not a target.
_LEARNING_BATCH = 200

#: How long a pool must keep reading gone before it is booked at $0. The
#: feed's own 120s confirmation is one snapshot for a token past 30 minutes
#: old, which the platform re-prices every 5 minutes; one `inactive` snapshot
#: is what made 6.9% of the platform Lab's zeros tokens that were still
#: trading. Ten minutes is two of those polls.
GONE_CONFIRMATION = timedelta(minutes=10)


def _dec(value) -> Decimal | None:
    return None if value is None else Decimal(value)


def _str(value) -> str | None:
    return None if value is None else str(value)


def _money(value: Decimal) -> Decimal:
    """At the column's precision, so this tick's arithmetic and the stored row
    (which later ticks' SQL sums read) agree to the cent and beyond."""
    return value.quantize(Decimal("0.0001"))


@dataclass
class BookState:
    """Everything a book remembers between ticks besides its positions."""

    ratchet: EquityRatchet
    death: DeathRateBreaker
    lrn: learning.Learning
    #: The multiplier last handed out, so a change can be audited.
    size_multiplier: float = 1.0
    day: date | None = None
    day_open_equity: Decimal | None = None
    #: Set when the daily breaker trips; latched until the day rolls.
    daily_halt: str | None = None

    @classmethod
    def load(cls, book: Book, saved: dict) -> BookState:
        r, d, lr = saved.get("ratchet"), saved.get("death"), saved.get("learning")
        lrn = learning.Learning(book=book.code)
        if lr:
            lrn.rug.strictness = Decimal(lr["rug_strictness"])
            lrn.rug._cut_but_recovered.extend(lr["cut_but_recovered"])
            lrn.rug._kept_but_died.extend(lr["kept_but_died"])
            lrn.lock.giveback = Decimal(lr["lock_giveback"])
            lrn.lock._locked_then_ran.extend(lr["locked_then_ran"])
            lrn.lock._unlocked_round_trips.extend(lr["unlocked_round_trips"])
            lrn.regime._recent.extend(lr["regime_recent"])
            lrn.regime._baseline = lr["regime_baseline"]
            for mint, t in lr["open_trades"].items():
                lrn.open_trades[mint] = learning.TradeRecord(
                    mint, datetime.fromisoformat(t["opened_at"]), Decimal(t["stake_usd"]),
                    _dec(t["entry_liquidity_usd"]), _dec(t["entry_market_cap_usd"]))
        return cls(
            ratchet=EquityRatchet(
                give_back=book.ratchet_give_back,
                high_water=Decimal(r["high_water"]) if r else book.starting_equity,
                floor=Decimal(r["floor"]) if r else book.ratchet_floor),
            death=DeathRateBreaker(
                window=book.death_window, halt_rate=book.death_rate,
                min_sample=book.death_min_sample, halt_for=book.death_halt_for,
                recent=d["recent"] if d else (),
                halted_until=(datetime.fromisoformat(d["halted_until"])
                              if d and d["halted_until"] else None),
                reason=d["reason"] if d else None),
            lrn=lrn,
            size_multiplier=saved.get("size_multiplier", 1.0),
            day=date.fromisoformat(saved["day"]) if saved.get("day") else None,
            day_open_equity=_dec(saved.get("day_open_equity")),
            daily_halt=saved.get("daily_halt"))

    def dump(self) -> dict:
        lrn = self.lrn
        return {
            "ratchet": {"high_water": str(self.ratchet.high_water),
                        "floor": str(self.ratchet.floor)},
            "death": {"recent": list(self.death.recent),
                      "halted_until": (self.death.halted_until.isoformat()
                                       if self.death.halted_until else None),
                      "reason": self.death.reason},
            "learning": {
                "rug_strictness": str(lrn.rug.strictness),
                "cut_but_recovered": list(lrn.rug._cut_but_recovered),
                "kept_but_died": list(lrn.rug._kept_but_died),
                "lock_giveback": str(lrn.lock.giveback),
                "locked_then_ran": list(lrn.lock._locked_then_ran),
                "unlocked_round_trips": list(lrn.lock._unlocked_round_trips),
                "regime_recent": list(lrn.regime._recent),
                "regime_baseline": lrn.regime._baseline,
                "open_trades": {m: {"opened_at": t.opened_at.isoformat(),
                                    "stake_usd": str(t.stake_usd),
                                    "entry_liquidity_usd": _str(t.entry_liquidity_usd),
                                    "entry_market_cap_usd": _str(t.entry_market_cap_usd)}
                                for m, t in lrn.open_trades.items()},
            },
            "size_multiplier": self.size_multiplier,
            "day": self.day.isoformat() if self.day else None,
            "day_open_equity": _str(self.day_open_equity),
            "daily_halt": self.daily_halt,
        }

    def halts(self, equity: Decimal, now: datetime) -> list[str]:
        """Why entries are held right now; empty when they are not."""
        out = []
        halted, why = self.death.check(now)
        if halted:
            out.append(f"death-rate breaker: {why}")
        halted, why = self.ratchet.check(equity)
        if halted:
            out.append(f"equity ratchet: {why}")
        if self.daily_halt:
            out.append(f"daily breaker: {self.daily_halt}")
        return out


def value(pos: Rafiqv2Position) -> Decimal:
    """What the part still held would fetch from its pool as last read: 0 once
    the pool reads gone. Never cost basis, never quantity x last price."""
    return costs.sell_proceeds(pos.quantity * pos.fraction_open,
                               pos.last_mark_price or pos.entry_price,
                               pos.last_mark_liquidity_usd)


def lock_floor(book: Book, pos: Rafiqv2Position) -> Decimal | None:
    """The multiple this position can no longer be sold below, if armed."""
    return ProfitLock(giveback=pos.lock_giveback,
                      ladder=book.lock_ladder).observe(pos.peak_price / pos.entry_price)


class Rafiqv2Service:
    """One tick's worth of work. Holds a session; writes only `rafiqv2_*`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._feed = RafiqFeed(session)
        #: One reading per token per tick, shared by every book.
        self._seen: dict[str, Observation | None] = {}

    async def activate(self, *, now: datetime) -> list[Rafiqv2Book]:
        """Create each book once; refuse a book whose rules have changed."""
        for book in config.BOOKS:
            await self._session.execute(
                pg_insert(Rafiqv2Book)
                .values(code=book.code, starting_equity=book.starting_equity,
                        config_digest=book.digest, activated_at=now)
                .on_conflict_do_nothing(index_elements=["code"]))
        await self._session.flush()
        rows = list((await self._session.execute(
            select(Rafiqv2Book).order_by(Rafiqv2Book.code))).scalars())
        drifted = [r.code for r in rows
                   if r.code not in config.BY_CODE
                   or r.config_digest != config.BY_CODE[r.code].digest]
        if drifted:
            raise RuntimeError(f"rafiqv2 books {drifted} were opened under other rules - "
                               "a changed rule is a new record, not an edit")
        return rows

    # --- reading a book ----------------------------------------------------

    async def cash(self, row: Rafiqv2Book) -> Decimal:
        """Starting capital less every entry plus every sale. Derived."""
        spent, back = (await self._session.execute(
            select(func.coalesce(func.sum(Rafiqv2Position.cost_basis), 0),
                   func.coalesce(func.sum(func.coalesce(Rafiqv2Position.exit_proceeds_usd,
                                                        Rafiqv2Position.realised_usd)), 0))
            .where(Rafiqv2Position.book_id == row.id))).one()
        return row.starting_equity - spent + back

    async def open_positions(self, row: Rafiqv2Book) -> list[Rafiqv2Position]:
        return list((await self._session.execute(
            select(Rafiqv2Position)
            .where(Rafiqv2Position.book_id == row.id, Rafiqv2Position.status == "open")
            .order_by(Rafiqv2Position.opened_at))).scalars())

    async def realised_on(self, row: Rafiqv2Book, day: date) -> Decimal:
        """P&L realised on `day`, each sale on the day it happened."""
        start = datetime.combine(day, time.min, tzinfo=UTC)
        total = Decimal(0)
        for p in (await self._session.execute(
                select(Rafiqv2Position).where(
                    Rafiqv2Position.book_id == row.id,
                    or_(Rafiqv2Position.closed_at >= start,
                        Rafiqv2Position.scaled_out_at >= start)))).scalars():
            if p.scaled_out_at is not None and p.scaled_out_at >= start:
                total += p.realised_usd - p.cost_basis * (1 - p.fraction_open)
            if p.closed_at is not None and p.closed_at >= start:
                total += p.exit_proceeds_usd - p.realised_usd - p.cost_basis * p.fraction_open
        return total

    # --- the tick ------------------------------------------------------------

    async def tick(self, *, now: datetime | None = None) -> dict:
        now = now or datetime.now(UTC)
        self._seen = {}
        if not (await self._session.execute(
                text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": _TICK_LOCK})).scalar():
            return {"skipped": "tick_in_progress"}
        rows = await self.activate(now=now)
        candidates = await self._feed.candidates(
            since=min(r.activated_at for r in rows),
            not_before=now - timedelta(seconds=MAX_CANDIDATE_AGE_SECONDS))
        report = {row.code: await self._tick_book(config.BY_CODE[row.code], row,
                                                  candidates, now=now)
                  for row in rows}
        await self._session.flush()
        return {"at": now.isoformat(), "books": report}

    async def _tick_book(self, book: Book, row: Rafiqv2Book,
                         candidates: list[Candidate], *, now: datetime) -> dict:
        st = BookState.load(book, row.state or {})
        held = await self.open_positions(row)
        closed = sum([await self._settle(book, row, st, pos, now=now) for pos in held])
        learned = await self._learn(row, st, now=now)
        # Sessions here run autoflush=False: the aggregates below must see
        # what this tick just closed.
        await self._session.flush()

        still = [p for p in held if p.status == "open"]
        cash = await self.cash(row)
        equity = cash + sum(map(value, still), Decimal(0))
        self._move_ratchet(book, row, st, equity, now=now)
        if st.day != now.date():
            st.day, st.day_open_equity, st.daily_halt = now.date(), equity, None
        if st.daily_halt is None:
            verdict = daily_verdict(
                DailyState(st.day, st.day_open_equity,
                           await self.realised_on(row, st.day)),
                now=now, cash=cash, open_position_values=list(map(value, still)),
                policy=book.daily)
            if verdict.halted:
                st.daily_halt = verdict.reason
                self._audit(row, now, "entries_halted", 0, 1,
                            f"daily breaker: {verdict.reason}")

        halts = st.halts(equity, now)
        opened, refused = 0, Counter()
        if not halts:
            opened, refused = await self._enter(book, row, st, candidates, cash=cash,
                                                equity=equity, now=now)
        row.state = st.dump()
        return {"closed": closed, "learned": learned, "opened": opened,
                "halted": halts, "refused": dict(refused)}

    async def _observe(self, mint: str, token_id, *, now: datetime) -> Observation | None:
        if mint not in self._seen:
            self._seen[mint] = await self._feed.observe(token_id=token_id, mint=mint, at=now)
        return self._seen[mint]

    # --- exits -------------------------------------------------------------

    async def _settle(self, book: Book, row: Rafiqv2Book, st: BookState,
                      pos: Rafiqv2Position, *, now: datetime) -> int:
        obs = await self._observe(pos.mint_address, pos.token_id, now=now)
        if obs is not None and obs.price_usd is None:
            # The pool reads gone: an `inactive` reading or a delisting after
            # its last tradeable print. Worth nothing meanwhile; booked at $0
            # once it has read gone since `GONE_CONFIRMATION` ago, not held to
            # the box, so the death-rate breaker counts it while it can still
            # stop the next entry. `last_evaluated_at` is the last tick that
            # found a tradeable print.
            pos.last_mark_liquidity_usd = Decimal(0)
            if now - pos.last_evaluated_at < GONE_CONFIRMATION:
                return 0
            return self._close(row, st, pos, reason="pool_gone", fill=Decimal(0),
                               liquidity=None, now=now,
                               evidence=("the pool has read gone since "
                                         f"{pos.last_evaluated_at:%H:%M:%S} UTC; "
                                         "nothing to sell into"))
        if obs is None:
            # Nothing has priced it lately. Staleness is not death: hold, and at
            # the box value it at what an unreadable pool pays, which is nothing.
            if now - pos.opened_at < book.max_hold:
                return 0
            return self._close(row, st, pos, reason="max_hold", fill=Decimal(0),
                               liquidity=None, now=now,
                               evidence=f"held to the {book.max_hold} box with no reading")
        if off_band(obs.price_usd, obs.median_price_10m):
            return 0  # a glitch print fills nothing and sets no peak

        pos.peak_price = max(pos.peak_price, obs.price_usd)
        pos.last_mark_price = obs.price_usd
        pos.last_mark_liquidity_usd = obs.liquidity_usd
        pos.last_evaluated_at = now
        d = engine.decide(book, entry_price=pos.entry_price, opened_at=pos.opened_at,
                          peak_price=pos.peak_price, scaled_out=pos.scaled_out,
                          fraction_open=pos.fraction_open,
                          rug_strictness=pos.rug_strictness,
                          lock_giveback=pos.lock_giveback, price=obs.price_usd, now=now)
        if d is None:
            return 0
        if d.reason == engine.SCALE_OUT:
            pos.realised_usd = _money(pos.realised_usd + costs.sell_proceeds(
                pos.quantity * d.fraction, d.fill, obs.liquidity_usd))
            pos.scaled_out, pos.scaled_out_at, pos.scale_out_price = True, now, d.fill
            pos.fraction_open -= d.fraction
            return 0
        return self._close(row, st, pos, reason=d.reason, fill=d.fill,
                           liquidity=obs.liquidity_usd, evidence=d.evidence, now=now)

    def _close(self, row: Rafiqv2Book, st: BookState, pos: Rafiqv2Position, *,
               reason: str, fill: Decimal, liquidity: Decimal | None, evidence: str,
               now: datetime) -> int:
        """Sell what is left into `liquidity` at `fill`. `fraction_open` keeps
        the slice this sale sold, so a scale-out's part stays separable."""
        pos.status, pos.closed_at = "closed", now
        pos.exit_price, pos.exit_reason, pos.exit_evidence = fill, reason, evidence
        pos.exit_proceeds_usd = _money(pos.realised_usd + costs.sell_proceeds(
            pos.quantity * pos.fraction_open, fill, liquidity))
        pos.died = fill <= pos.entry_price * outcomes.ZERO_MULTIPLE
        halt = st.death.record(token_died=pos.died, now=now)
        if halt:
            self._audit(row, now, "entries_halted", 0, 1, f"death-rate breaker: {halt}")
        return 1

    # --- learning ----------------------------------------------------------

    async def _learn(self, row: Rafiqv2Book, st: BookState, *, now: datetime) -> int:
        """`on_exit` for every close whose hour after exit has closed.

        The hour is what lets the learner ask its questions at all: "did a cut
        token recover" and "did a locked token keep running" are both about
        prices after the sale, so the peak it is handed is the best of the
        hold and the hour after. `lock_armed` is passed as "the lock sold it",
        the event its docstring describes ("locks are firing"); a position
        that armed the lock and then rugged through the stop is not evidence
        the lock was too tight.
        """
        due = list((await self._session.execute(
            select(Rafiqv2Position)
            .where(Rafiqv2Position.book_id == row.id, Rafiqv2Position.status == "closed",
                   Rafiqv2Position.learning_recorded_at.is_(None),
                   Rafiqv2Position.closed_at <= now - outcomes.EXIT_WINDOW)
            .order_by(Rafiqv2Position.closed_at).limit(_LEARNING_BATCH))).scalars())
        for pos in due:
            window = await self._feed.forward_window(
                mint=pos.mint_address, after=pos.closed_at,
                until=pos.closed_at + outcomes.EXIT_WINDOW)
            prices = [r.price_usd for r in window if tradeable(r)]
            pos.forward_peak_multiple = max(prices) / pos.entry_price if prices else None
            held_peak = pos.peak_price / pos.entry_price
            made = st.lrn.on_exit(
                pos.mint_address, closed_at=pos.closed_at, exit_reason=pos.exit_reason,
                net_return=pos.exit_proceeds_usd / pos.cost_basis - 1,
                peak_multiple=max(held_peak, pos.forward_peak_multiple or held_peak),
                token_died=pos.died, lock_armed=pos.exit_reason == engine.LOCK)
            pos.learning_recorded_at = now
            for a in made:
                self._audit(row, now, a.parameter, a.old_value, a.new_value, a.reason,
                            sample_size=a.sample_size, z_score=a.z_score)
        return len(due)

    def _audit(self, row: Rafiqv2Book, at: datetime, parameter: str, old, new,
               reason: str, *, sample_size: int | None = None,
               z_score: float | None = None) -> None:
        self._session.add(Rafiqv2Adjustment(
            book_id=row.id, at=at, parameter=parameter, old_value=Decimal(str(old)),
            new_value=Decimal(str(new)), sample_size=sample_size,
            z_score=None if z_score is None else Decimal(str(z_score)), reason=reason))
        logger.info("rafiqv2_adjustment", book=row.code, parameter=parameter,
                    old=str(old), new=str(new), sample_size=sample_size,
                    z_score=z_score, reason=reason)

    def _move_ratchet(self, book: Book, row: Rafiqv2Book, st: BookState,
                      equity: Decimal, *, now: datetime) -> None:
        before = st.ratchet.floor
        st.ratchet.update(equity)
        if st.ratchet.floor != before:
            self._audit(row, now, "equity_ratchet_floor", before, st.ratchet.floor,
                        f"equity ${equity:,.2f} is a new high; floor = high less "
                        f"{book.ratchet_give_back:.0%}, never down")

    # --- entries -----------------------------------------------------------

    async def _enter(self, book: Book, row: Rafiqv2Book, st: BookState,
                     candidates: list[Candidate], *, cash: Decimal, equity: Decimal,
                     now: datetime) -> tuple[int, Counter]:
        refused: Counter = Counter()
        fresh = [c for c in candidates if c.detected_at > row.activated_at]
        traded = set((await self._session.execute(
            select(Rafiqv2Position.mint_address)
            .where(Rafiqv2Position.book_id == row.id,
                   Rafiqv2Position.mint_address.in_([c.mint_address for c in fresh]))
        )).scalars()) if fresh else set()
        opened = 0
        for cand in fresh:
            if cand.mint_address in traded:
                continue
            if cand.opportunity_score < book.score_min:
                refused["score_below_threshold"] += 1
                continue
            obs = await self._observe(cand.mint_address, cand.token_id, now=now)
            if obs is None or not obs.is_tradeable:
                refused["not_tradeable"] += 1
                continue
            if (now - obs.observed_at).total_seconds() > STALE_GUARD_SECONDS:
                refused["observation_stale"] += 1
                continue

            # Read immediately before this decision; frozen onto the position.
            params = st.lrn.current_parameters()
            if params["size_multiplier"] != st.size_multiplier:
                self._audit(row, now, "size_multiplier", st.size_multiplier,
                            params["size_multiplier"], params["regime_note"],
                            sample_size=st.lrn.regime.sample_size)
                st.size_multiplier = params["size_multiplier"]
            multiplier = Decimal(str(params["size_multiplier"]))
            notional = min(book.size_max, max(book.size_min,
                           equity * book.size_pct * multiplier)).quantize(Decimal("0.01"))
            if notional > cash:
                refused["insufficient_cash"] += 1
                continue
            verdict = entry_gate.check_entry(
                liquidity_usd=obs.liquidity_usd, market_cap_usd=obs.market_cap,
                notional_usd=notional, thresholds=book.gate)
            if not verdict.allowed:
                refused[verdict.reason] += 1
                continue
            quantity = costs.buy_quantity(notional, obs.price_usd, obs.liquidity_usd)
            if not quantity:
                refused["unquantifiable"] += 1
                continue
            # The ratchet, checked before every entry: each buy moves equity.
            self._move_ratchet(book, row, st, equity, now=now)
            if st.ratchet.check(equity)[0]:
                refused["equity_ratchet"] += 1
                break

            features = await self._feed.entry_features(mint=cand.mint_address, at=now)
            self._session.add(Rafiqv2Position(
                book_id=row.id, mint_address=cand.mint_address, token_id=cand.token_id,
                symbol=cand.symbol, detected_at=cand.detected_at, opened_at=now,
                entry_price=notional / quantity, entry_observed_price=obs.price_usd,
                quantity=quantity, cost_basis=notional,
                entry_liquidity_usd=obs.liquidity_usd, entry_market_cap_usd=obs.market_cap,
                entry_impact_pct=verdict.entry_impact_pct,
                entry_score=cand.opportunity_score,
                entry_top10_holder_pct=features.top10_holder_pct,
                entry_lp_locked=features.lp_locked,
                entry_features_error=features.error,
                rug_strictness=Decimal(str(params["rug_strictness"])),
                lock_giveback=Decimal(str(params["lock_giveback"])),
                size_multiplier=multiplier, status="open", peak_price=obs.price_usd,
                last_mark_price=obs.price_usd, last_mark_liquidity_usd=obs.liquidity_usd,
                last_evaluated_at=now, scaled_out=False, fraction_open=Decimal(1),
                realised_usd=Decimal(0)))
            st.lrn.on_entry(learning.TradeRecord(cand.mint_address, now, notional,
                                                 obs.liquidity_usd, obs.market_cap))
            opened += 1
            traded.add(cand.mint_address)
            cash -= notional
            equity += (costs.sell_proceeds(quantity, obs.price_usd, obs.liquidity_usd)
                       - notional)
        if opened:
            self._move_ratchet(book, row, st, equity, now=now)
        return opened, refused
