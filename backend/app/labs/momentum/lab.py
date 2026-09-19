"""The Momentum Lab: universe, samples, candles, and fifty paper books.

## One tick, every thirty seconds

1. poll every watched pool (by address, 30 a call);
2. fill what was decided LAST tick, exit what is due, trigger stops;
3. fold the samples into five-minute candles;
4. when a 5m / 15m / 1h bar has just closed, judge it for every strategy and
   the controls, and queue the buys.

A buy decided now fills on the NEXT tick's sample for that pool — a price
fetched after the decision, describing the market ~3 seconds after it (the
feed runs ~27s behind). No strategy ever buys at a price it used to decide.

## Paper only

No key, no signer, no route to a wallet. Every trade is measured at
`TICKET_USD`; the $1,000 wallets and their splits are walked from those trades
by `board.py`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Any

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.labs.momentum import config
from app.labs.momentum.arms import (
    ARMS,
    BY_NAME,
    IMPULSE_RET,
    Arm,
    Context,
    Rolling,
    bar_key,
    coin,
    fires,
    fires_rolling,
)
from app.labs.momentum.candles import Bar, Features, bucket, features
from app.labs.momentum.models import (
    MomCandle,
    MomClose,
    MomPair,
    MomPosition,
    MomSignal,
)
from app.labs.momentum.sources import Feeds, PairRow, best_pair

logger = get_logger(__name__)

LIVE = ("armed", "pending", "open", "closing")
#: One judged pool: (address, the bar's features, the bar before's, context).
Judged = tuple[str, Features, Features | None, Context]
_P = Decimal("1E-18")


# --- execution arithmetic ----------------------------------------------------------

def impact(order_usd: Decimal, liquidity: Decimal | None) -> Decimal | None:
    """Constant-product price move of an order against a pool's quote side
    (half its reported total). Overstates it for concentrated pools, which
    is the safe direction for a book."""
    if liquidity is None or liquidity <= 0:
        return None
    return order_usd / (liquidity / 2)


def buy(price: Decimal, liquidity: Decimal | None, fee_bps: int,
        notional: Decimal) -> tuple[Decimal, Decimal, Decimal] | None:
    """(fill price, tokens, impact) for a buy of `notional` dollars."""
    moved = impact(notional, liquidity)
    if moved is None or moved > config.MAX_IMPACT or price <= 0:
        return None
    fill = price * (1 + Decimal(fee_bps) / 10_000) * (1 + moved)
    tokens = (notional - config.NETWORK_FEE_USD) / fill
    return fill, tokens, moved


def sell(price: Decimal, liquidity: Decimal | None, fee_bps: int,
         tokens: Decimal) -> tuple[Decimal, Decimal, Decimal | None]:
    """(fill price, dollar proceeds, impact) for selling `tokens`. Always
    fills: a position has to leave. With no depth on record, fees only."""
    value = tokens * price
    moved = impact(value, liquidity)
    fill = price * (1 - Decimal(fee_bps) / 10_000) / (1 + (moved or 0))
    return fill, max(tokens * fill - config.NETWORK_FEE_USD, Decimal(0)), moved


# --- samples -------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Sample:
    row: PairRow
    price: Decimal
    #: When the market was at this price: fetch time minus the feed lag.
    at: datetime
    fetched_at: datetime


def _q(value: Decimal | None, places: Decimal = _P) -> Decimal | None:
    return None if value is None else value.quantize(places)


class MomentumLab:
    """Every strategy, one tick."""

    def __init__(self, session: AsyncSession, *, feeds: Feeds,
                 now: datetime | None = None) -> None:
        self._s = session
        self._feeds = feeds
        self._now = now or datetime.now(UTC)
        #: The newest fetch this tick: decisions taken now are stamped with
        #: it, so only a LATER fetch can fill them.
        self._seen = self._now
        self._sol_usd: Decimal | None = None
        self._breadth: float | None = None

    # ==== the universe (every 30 minutes) =====================================

    async def refresh_universe(self, *, max_resolve: int = 200) -> dict[str, Any]:
        listed = await self._feeds.listed()
        if not listed:
            return {"listed": 0, "skipped": "no_lists_answered"}
        cutoff = self._now - timedelta(days=config.MIN_AGE_DAYS)
        by_mint: dict[str, dict[str, Any]] = {}
        for item in listed:
            entry = by_mint.setdefault(item.mint, {
                "symbol": item.symbol, "born": item.born_at, "liq": item.liquidity,
                "tags": set(), "lists": set()})
            entry["tags"] |= item.tags
            entry["lists"].add(item.list_name)
            if item.born_at and (entry["born"] is None or item.born_at < entry["born"]):
                entry["born"] = item.born_at
            if item.liquidity and (entry["liq"] is None or item.liquidity > entry["liq"]):
                entry["liq"] = item.liquidity
        eligible = {m: e for m, e in by_mint.items()
                    if m not in config.EXCLUDED_MINTS
                    and not (e["tags"] & config.EXCLUDED_TAGS)
                    and e["born"] is not None and e["born"] <= cutoff
                    and (e["liq"] or 0) >= config.MIN_LIQUIDITY_USD}
        rows = (await self._s.scalars(
            select(MomPair).where(MomPair.mint.in_(list(eligible))))).all()
        active = {r.mint: r for r in rows if r.status == "active"}
        admitted = refreshed = unresolved = 0
        for mint, e in eligible.items():
            row = active.get(mint)
            if row is not None:
                row.listed_at = self._now
                row.lists = sorted(e["lists"])
                refreshed += 1
                continue
            if admitted + unresolved >= max_resolve:
                continue
            pair = best_pair(await self._feeds.token_pairs(mint), mint)
            if pair is None:
                unresolved += 1
                continue
            existing = await self._s.get(MomPair, pair.pair_address)
            if existing is not None:
                existing.status, existing.drop_reason = "active", None
                existing.listed_at = self._now
                existing.lists = sorted(e["lists"])
            else:
                self._s.add(MomPair(
                    pair_address=pair.pair_address, mint=mint,
                    symbol=(e["symbol"] or pair.symbol or "")[:32] or None,
                    dex_id=pair.dex_id, quote_mint=pair.quote_mint,
                    born_at=e["born"], status="active", lists=sorted(e["lists"]),
                    admitted_at=self._now, listed_at=self._now,
                    liquidity_usd=pair.liquidity, volume_h24=pair.volume_h24))
            admitted += 1
        # Off every list for a while: stop polling. A position still open on
        # it keeps its pool polled regardless (`_watched`).
        stale = await self._s.execute(
            update(MomPair)
            .where(MomPair.status == "active",
                   MomPair.listed_at < self._now - timedelta(hours=config.UNIVERSE_TTL_HOURS))
            .values(status="dropped", drop_reason="unlisted"))
        await self._s.flush()
        over = (await self._s.scalars(
            select(MomPair.pair_address).where(MomPair.status == "active")
            .order_by(MomPair.listed_at.desc(), MomPair.volume_h24.desc().nulls_last())
            .offset(config.MAX_PAIRS))).all()
        if over:
            await self._s.execute(update(MomPair).where(MomPair.pair_address.in_(over))
                                  .values(status="dropped", drop_reason="cap"))
        result = {"listed": len(by_mint), "eligible": len(eligible),
                  "admitted": admitted, "refreshed": refreshed,
                  "unresolved": unresolved, "unlisted": stale.rowcount or 0,
                  "capped": len(over), "calls": dict(self._feeds.calls)}
        logger.info("momentum_universe", **result)
        return result

    # ==== the tick =============================================================

    async def tick(self) -> dict[str, Any]:
        pairs = await self._watched()
        if not pairs:
            return {"pairs": 0, "skipped": "empty_universe"}
        rows = await self._feeds.pairs(list(pairs))
        samples = self._accept(pairs, rows)
        if samples:
            self._seen = max(s.fetched_at for s in samples.values())
        self._market(samples)
        live = (await self._s.scalars(
            select(MomPosition).where(MomPosition.status.in_(LIVE)))).all()
        filled, closed = self._manage(live, pairs, samples)
        await self._write_candles(pairs, samples)
        self._mark_pairs(pairs, samples)
        opened: dict[str, int] = defaultdict(int)
        judged = {}
        m_now = self._now - timedelta(seconds=config.FEED_LAG_S)
        for tf, secs in config.TIMEFRAMES.items():
            start = bucket(m_now, secs) - timedelta(seconds=secs)
            judged[tf] = await self._judge(tf, secs, start, pairs, live, opened)
        await self._catch(pairs, samples, live, opened)
        await self._s.flush()
        result = {"pairs": len(pairs), "sampled": len(samples),
                  "calls": self._feeds.calls["dex"], "failures": self._feeds.failures,
                  "filled": filled, "closed": closed, "opened": sum(opened.values()),
                  "judged": {k: v for k, v in judged.items() if v is not None}}
        logger.info("momentum_tick", **result)
        return result

    async def _watched(self) -> dict[str, MomPair]:
        """Active pools, plus any pool a live position still needs marked."""
        held = select(MomPosition.pair_address).where(MomPosition.status.in_(LIVE))
        rows = (await self._s.scalars(
            select(MomPair).where((MomPair.status == "active")
                                  | MomPair.pair_address.in_(held)))).all()
        return {r.pair_address: r for r in rows}

    def _accept(self, pairs: dict[str, MomPair],
                rows: dict[str, PairRow]) -> dict[str, Sample]:
        """This tick's samples that may be used: the right token, a price, and
        not a glitch print."""
        out: dict[str, Sample] = {}
        lag = timedelta(seconds=config.FEED_LAG_S)
        for address, row in rows.items():
            pair = pairs.get(address)
            if pair is None or row.base_mint != pair.mint:
                continue
            price = row.price_usd
            if price is None or price <= 0 or row.fetched_at is None:
                continue
            at = row.fetched_at - lag
            last, last_at = pair.last_price, pair.last_sample_at
            if (last and last_at and at - last_at < timedelta(minutes=2)
                    and price > last * config.GLITCH_UP_X):
                pair.glitches = (pair.glitches or 0) + 1
                logger.warning("momentum_glitch_refused", pair=address,
                               last=str(last), price=str(price))
                continue
            out[address] = Sample(row, price, at, row.fetched_at)
        return out

    def _market(self, samples: dict[str, Sample]) -> None:
        """SOL in dollars and the share of the universe up on the hour, from
        this tick's own samples."""
        rates = [s.row.price_usd / s.row.price_native for s in samples.values()
                 if s.row.quote_mint == config.WSOL_MINT and s.row.price_native
                 and s.row.price_native > 0 and s.row.price_usd]
        self._sol_usd = Decimal(median(rates)) if rates else None
        changes = [s.row.change_h1 for s in samples.values() if s.row.change_h1 is not None]
        self._breadth = (sum(1 for c in changes if c > 0) / len(changes)) if changes else None

    def _mark_pairs(self, pairs: dict[str, MomPair], samples: dict[str, Sample]) -> None:
        for address, s in samples.items():
            pair = pairs[address]
            pair.last_price = _q(s.price)
            pair.last_sample_at = s.at
            pair.liquidity_usd = s.row.liquidity
            pair.volume_h24 = s.row.volume_h24
            pair.change_h1 = s.row.change_h1
            if (pair.status == "active" and s.row.liquidity is not None
                    and s.row.liquidity < config.MIN_PAIR_LIQUIDITY_USD):
                pair.status, pair.drop_reason = "dropped", "thin"

    async def _write_candles(self, pairs: dict[str, MomPair],
                             samples: dict[str, Sample]) -> None:
        """Fold each sample into its pool's five-minute candle, in one statement.

        A new candle OPENS at the previous sample's price when that sample is
        recent, so consecutive candles join and no move falls between two.
        Every row carries every key: a multi-row insert takes its columns from
        the FIRST row and silently drops keys the others add.
        """
        if not samples:
            return
        values = []
        for address, s in samples.items():
            pair = pairs[address]
            opened = s.price
            if (pair.last_price and pair.last_sample_at
                    and timedelta(0) < s.at - pair.last_sample_at <= timedelta(minutes=2)):
                opened = pair.last_price
            values.append({
                "pair_address": address, "start": bucket(s.at, config.BASE_BAR_S),
                "open": _q(opened), "high": _q(max(opened, s.price)),
                "low": _q(min(opened, s.price)), "close": _q(s.price),
                "volume_usd": s.row.volume_m5, "buys": s.row.buys_m5,
                "sells": s.row.sells_m5, "volume_h24": s.row.volume_h24,
                "liquidity_usd": s.row.liquidity, "change_h24": s.row.change_h24,
                "samples": 1})
        stmt = pg_insert(MomCandle).values(values)
        x = stmt.excluded
        await self._s.execute(stmt.on_conflict_do_update(
            index_elements=[MomCandle.pair_address, MomCandle.start],
            set_={"high": func.greatest(MomCandle.high, x.close),
                  "low": func.least(MomCandle.low, x.close),
                  "close": x.close, "volume_usd": x.volume_usd, "buys": x.buys,
                  "sells": x.sells, "volume_h24": x.volume_h24,
                  "liquidity_usd": x.liquidity_usd, "change_h24": x.change_h24,
                  "samples": MomCandle.samples + 1}))

    # ==== positions ===============================================================

    def _manage(self, live: Sequence[MomPosition], pairs: dict[str, MomPair],
                samples: dict[str, Sample]) -> tuple[int, int]:
        filled = closed = 0
        for p in live:
            arm = BY_NAME.get(p.arm)
            s = samples.get(p.pair_address)
            pair = pairs.get(p.pair_address)
            if arm is None:
                # Retired while live: settle at the last price and say so.
                if p.status in ("open", "closing") and pair and pair.last_price:
                    self._close(p, pair.last_price, pair.liquidity_usd,
                                pair.last_sample_at or self._now, "arm_retired")
                    closed += 1
                elif p.status in ("armed", "pending"):
                    self._void(p, "arm_retired")
                continue
            if p.status == "armed":
                if self._now >= (p.expires_at or self._now):
                    self._void(p, "expired")
                elif s is not None and s.price <= (p.trigger_below or 0):
                    p.status, p.decided_at = "pending", s.fetched_at
                continue
            if p.status == "pending":
                if s is not None and s.fetched_at > p.decided_at:
                    filled += self._fill(p, s, pair)
                elif (self._now - p.decided_at).total_seconds() > config.ENTRY_MAX_WAIT_S:
                    self._void(p, "no_fresh_price")
                continue
            if p.status == "closing":
                if s is not None and s.fetched_at > (p.exit_decided_at or self._now):
                    self._close(p, s.price, s.row.liquidity, s.at, p.exit_reason or "exit")
                    closed += 1
                elif (self._now - (p.exit_decided_at or self._now)).total_seconds() \
                        > config.EXIT_MAX_WAIT_S and pair and pair.last_price:
                    self._close(p, pair.last_price, pair.liquidity_usd,
                                pair.last_sample_at or self._now, p.exit_reason or "exit")
                    closed += 1
                continue
            # open
            if s is None:
                last = pair.last_sample_at if pair else None
                if (last is None or (self._now - last).total_seconds()
                        > config.NO_DATA_CLOSE_S) and pair and pair.last_price:
                    self._close(p, pair.last_price, pair.liquidity_usd,
                                last or self._now, "no_data")
                    closed += 1
                continue
            closed += self._watch(p, arm, s)
        return filled, closed

    def _fill(self, p: MomPosition, s: Sample, pair: MomPair | None) -> int:
        arm = BY_NAME[p.arm]
        fee = config.fee_bps(p.dex_id, self._mcap_sol(s.row))
        done = buy(s.price, s.row.liquidity, fee, p.notional_usd)
        if done is None:
            self._void(p, "unfillable")
            return 0
        fill, tokens, moved = done
        p.status, p.opened_at = "open", s.at
        p.open_price, p.open_fill = _q(s.price), _q(fill)
        p.tokens = tokens.quantize(Decimal("1E-12"))
        p.fee_bps, p.liq_open_usd = fee, s.row.liquidity
        p.impact_open = moved.quantize(Decimal("1E-8"))
        p.peak_price = _q(s.price)
        stop = {"low": p.signal_low,
                "mid": (p.signal_high + p.signal_low) / 2}.get(arm.stop or "")
        if stop is not None:
            p.stop_price = _q(stop)
            risk = s.price - stop
            if risk > 0 and arm.target_r:
                p.target_price = _q(s.price + risk * (1 if arm.scale else arm.target_r))
        return 1

    def _watch(self, p: MomPosition, arm: Arm, s: Sample) -> int:
        """Mark an open position; close it if its clock is up, or decide an
        exit that the NEXT sample will fill."""
        price = s.price
        if p.peak_price is None or price > p.peak_price:
            p.peak_price = _q(price)
        # Scale-out: the half decided last tick is sold on this sample.
        if p.scaled_at is not None and p.scaled_usd is None and s.fetched_at > p.scaled_at:
            half = (p.tokens or 0) / 2
            _, proceeds, _ = sell(price, s.row.liquidity, p.fee_bps or config.FEE_BPS, half)
            p.scaled_usd = proceeds.quantize(Decimal("1E-6"))
            p.tokens = (p.tokens or 0) - half
            # The rest can no longer lose: its stop moves to the entry.
            p.stop_price = p.open_price
            if p.open_price is not None and p.stop_price is not None and arm.target_r:
                risk = p.open_price - (p.signal_low or p.open_price)
                if risk > 0:
                    p.target_price = _q(p.open_price + risk * arm.target_r)
        due = (p.opened_at or self._now) + timedelta(seconds=arm.hold * arm.bar_seconds)
        if s.at >= due:
            self._close(p, price, s.row.liquidity, s.at, "time")
            return 1
        reason = None
        if p.stop_price is not None and price <= p.stop_price:
            reason = "breakeven" if p.scaled_usd is not None else "stop"
        elif arm.trail and p.peak_price and price <= p.peak_price * (1 - arm.trail):
            reason = "trail"
        elif arm.scale and p.scaled_at is None and p.target_price and price >= p.target_price:
            p.scaled_at = s.fetched_at          # half goes next tick
        elif p.target_price is not None and price >= p.target_price and (
                not arm.scale or p.scaled_usd is not None):
            reason = "target"
        elif arm.tp and p.open_price and price >= p.open_price * (1 + arm.tp):
            reason = "take_profit"
        if reason:
            p.status, p.exit_reason, p.exit_decided_at = "closing", reason, s.fetched_at
        return 0

    def _close(self, p: MomPosition, price: Decimal, liquidity: Decimal | None,
               at: datetime, reason: str) -> None:
        fee = p.fee_bps or config.FEE_BPS
        fill, proceeds, moved = sell(price, liquidity, fee, p.tokens or Decimal(0))
        total = proceeds + (p.scaled_usd or 0)
        net = total / p.notional_usd - 1
        p.status, p.closed_at, p.exit_reason = "closed", at, reason
        p.close_price, p.close_fill = _q(price), _q(fill)
        p.liq_close_usd = liquidity
        p.impact_close = None if moved is None else moved.quantize(Decimal("1E-8"))
        p.net_return = net.quantize(Decimal("1E-8"))
        p.pnl_usd = (p.notional_usd * net).quantize(Decimal("0.01"))

    def _void(self, p: MomPosition, reason: str) -> None:
        """Terminal and counted nowhere: no fill ever happened."""
        p.status, p.exit_reason, p.closed_at = "unfilled", reason, self._now

    def _mcap_sol(self, row: PairRow) -> Decimal | None:
        if row.market_cap is None or not self._sol_usd:
            return None
        return row.market_cap / self._sol_usd

    # ==== judging closed bars =========================================================

    async def _judge(self, tf: str, secs: int, start: datetime,
                     pairs: dict[str, MomPair], live: Sequence[MomPosition],
                     opened: dict[str, int]) -> dict[str, Any] | None:
        """Judge the `tf` bar that began at `start`, once, if it has closed."""
        claimed = (await self._s.execute(
            pg_insert(MomClose).values(tf=tf, start=start, evaluated_at=self._now)
            .on_conflict_do_nothing().returning(MomClose.tf))).first()
        if claimed is None:
            return None
        active = {a: p for a, p in pairs.items() if p.status == "active"}
        history = await self._bars(tf, secs, start, list(active))
        prior_rate = await self._rates(tf)
        arms = [a for a in ARMS if a.tf == tf]
        rule_arms = [a for a in arms if a.rule is not None]
        eligible: list[Judged] = []
        for address, bars in history.items():
            bar = bars[-1] if bars and bars[-1].start == start else None
            if bar is None or not self._judgeable(bar, tf):
                continue
            pair = active[address]
            if bar.liquidity is None or bar.liquidity < float(config.MIN_LIQUIDITY_USD):
                continue
            prior = bars[:-1]
            f = features(bar, prior, secs, impulse_ret=IMPULSE_RET[tf])
            if f.history < config.MIN_HISTORY_BARS:
                continue
            prev = (features(prior[-1], prior[:-1], secs, impulse_ret=IMPULSE_RET[tf])
                    if prior and prior[-1].start == start - timedelta(seconds=secs) else None)
            ctx = Context(liquidity=bar.liquidity,
                          age_days=(start - pair.born_at).total_seconds() / 86_400,
                          breadth=self._breadth)
            eligible.append((address, f, prev, ctx))
        fired: dict[str, list[str]] = {a.name: [] for a in rule_arms}
        for address, f, prev, ctx in eligible:
            for arm in rule_arms:
                if fires(arm.rule, f, ctx, prev=prev):
                    fired[arm.name].append(address)
        counts = {name: len(v) for name, v in fired.items() if v}
        green = sum(1 for _, f, _, _ in eligible if f.green)
        await self._s.execute(
            update(MomClose).where(MomClose.tf == tf, MomClose.start == start)
            .values(eligible=len(eligible), green=green, fired=counts))
        # The controls, off the SAME eligible set.
        for arm in arms:
            if arm.control is None:
                continue
            base = counts.get(arm.matches or "", 0)
            pool = [e for e in eligible if e[1].green] if arm.control == "green" else eligible
            if arm.control == "same":
                ranked = sorted(pool, key=lambda e: coin(arm.name, bar_key(e[0], start)))
                fired[arm.name] = [e[0] for e in ranked[:base]]
            else:
                seen, hits, greens = prior_rate.get(arm.matches or "", (0, 0, 0))
                denominator = ((greens + green) if arm.control == "green"
                               else (seen + len(eligible)))
                p = (hits + base) / denominator if denominator else 0.0
                fired[arm.name] = [e[0] for e in pool
                                   if coin(arm.name, bar_key(e[0], start)) < p]
        by_address = {e[0]: e for e in eligible}
        await self._red_exits(tf, start, history, live)
        taken = await self._enter(start, tf, fired, by_address, pairs, live, opened)
        await self._record_signals(tf, start, fired, by_address, pairs)
        return {"eligible": len(eligible), "fired": sum(1 for v in fired.values() if v),
                "opened": taken}

    def _judgeable(self, bar: Bar, tf: str) -> bool:
        if tf == "5m":
            return bar.samples >= config.MIN_SAMPLES_5M
        need = config.TIMEFRAMES[tf] // config.BASE_BAR_S
        return bar.parts >= float(config.MIN_COVERAGE) * need

    async def _bars(self, tf: str, secs: int, start: datetime,
                    addresses: Sequence[str]) -> dict[str, list[Bar]]:
        """Each pool's bars up to and including `start`, oldest first: the
        stored 5m candles, or 15m/1h bars aggregated from them in SQL."""
        if not addresses:
            return {}
        n = config.TREND_BARS + 1 if tf == "5m" else config.LOOKBACK_BARS + 1
        since = start - timedelta(seconds=secs * (n - 1))
        until = start + timedelta(seconds=secs)
        rows = (await self._s.execute(text("""
            SELECT pair_address,
                   to_timestamp(floor(extract(epoch FROM start) / :secs) * :secs) AS b,
                   (array_agg(open ORDER BY start))[1] AS open,
                   max(high) AS high, min(low) AS low,
                   (array_agg(close ORDER BY start DESC))[1] AS close,
                   sum(volume_usd) AS volume_usd, sum(buys) AS buys, sum(sells) AS sells,
                   (array_agg(volume_h24 ORDER BY start DESC))[1] AS volume_h24,
                   (array_agg(liquidity_usd ORDER BY start DESC))[1] AS liquidity_usd,
                   (array_agg(change_h24 ORDER BY start DESC))[1] AS change_h24,
                   sum(samples) AS samples, count(*) AS parts
            FROM mom_candles
            WHERE pair_address = ANY(:pairs) AND start >= :since AND start < :until
            GROUP BY pair_address, b
            ORDER BY pair_address, b
        """), {"secs": secs, "pairs": list(addresses), "since": since, "until": until})).all()
        out: dict[str, list[Bar]] = defaultdict(list)

        def f(v: Any) -> float | None:
            return None if v is None else float(v)

        for r in rows:
            out[r.pair_address].append(Bar(
                start=r.b, open=float(r.open), high=float(r.high), low=float(r.low),
                close=float(r.close), volume=f(r.volume_usd),
                buys=None if r.buys is None else int(r.buys),
                sells=None if r.sells is None else int(r.sells),
                volume_h24=f(r.volume_h24), liquidity=f(r.liquidity_usd),
                change_h24=f(r.change_h24), samples=int(r.samples), parts=int(r.parts)))
        return out

    async def _rates(self, tf: str) -> dict[str, tuple[int, int, int]]:
        """Per rule, over the last day of `tf` closes: (bars judged, times the
        rule fired, green bars judged) — what a random control's rate is."""
        closes = (await self._s.execute(
            select(MomClose.eligible, MomClose.green, MomClose.fired)
            .where(MomClose.tf == tf, MomClose.start >= self._now - timedelta(days=1)))).all()
        seen = sum(c.eligible for c in closes)
        greens = sum(c.green for c in closes)
        out: dict[str, tuple[int, int, int]] = {}
        for arm in ARMS:
            if arm.tf == tf and arm.rule is not None:
                hits = sum(int((c.fired or {}).get(arm.name, 0)) for c in closes)
                out[arm.name] = (seen, hits, greens)
        return out

    async def _red_exits(self, tf: str, start: datetime, history: dict[str, list[Bar]],
                         live: Sequence[MomPosition]) -> None:
        secs = config.TIMEFRAMES[tf]
        for p in live:
            arm = BY_NAME.get(p.arm)
            if (arm is None or not arm.red_exit or arm.tf != tf or p.status != "open"
                    or p.opened_at is None):
                continue
            bars = history.get(p.pair_address) or []
            bar = bars[-1] if bars and bars[-1].start == start else None
            # A candle that CLOSED after the fill, and closed red.
            if bar and start + timedelta(seconds=secs) > p.opened_at and bar.close < bar.open:
                p.status, p.exit_reason = "closing", "red_candle"
                p.exit_decided_at = self._seen

    async def _enter(self, start: datetime, tf: str, fired: dict[str, list[str]],
                     eligible: dict[str, Judged],
                     pairs: dict[str, MomPair], live: Sequence[MomPosition],
                     opened: dict[str, int]) -> int:
        holding = {(p.arm, p.pair_address) for p in live if p.status in LIVE}
        counts: dict[str, int] = defaultdict(int)
        for p in live:
            if p.status in LIVE:
                counts[p.arm] += 1
        taken = 0
        for name, addresses in fired.items():
            arm = BY_NAME[name]
            for address in addresses:
                if (name, address) in holding or counts[name] >= config.MAX_OPEN_PER_ARM:
                    continue
                _, f, prev, _ = eligible[address]
                pair = pairs[address]
                bar = f.bar
                pullback = arm.rule is not None and arm.rule.pullback
                self._s.add(MomPosition(
                    arm=name, pair_address=address, mint=pair.mint, symbol=pair.symbol,
                    dex_id=pair.dex_id, status="armed" if pullback else "pending",
                    signal_tf=tf, signal_start=start,
                    signal_open=_q(Decimal(repr(bar.open))),
                    signal_high=_q(Decimal(repr(bar.high))),
                    signal_low=_q(Decimal(repr(bar.low))),
                    signal_close=_q(Decimal(repr(bar.close))),
                    features={**f.as_json(), **({"prev": prev.as_json()} if prev else {})},
                    decided_at=self._seen,
                    trigger_below=(_q(Decimal(repr((bar.high + bar.low) / 2)))
                                   if pullback else None),
                    expires_at=(self._seen + timedelta(seconds=3 * config.TIMEFRAMES[tf])
                                if pullback else None),
                    notional_usd=config.TICKET_USD))
                holding.add((name, address))
                counts[name] += 1
                opened[name] += 1
                taken += 1
        return taken

    async def _record_signals(self, tf: str, start: datetime, fired: dict[str, list[str]],
                              eligible: dict[str, Judged],
                              pairs: dict[str, MomPair]) -> None:
        by_pair: dict[str, list[str]] = defaultdict(list)
        for name, addresses in fired.items():
            if BY_NAME[name].is_control:
                continue
            for address in addresses:
                by_pair[address].append(name)
        for address, names in by_pair.items():
            f = eligible[address][1]
            self._s.add(MomSignal(
                pair_address=address, mint=pairs[address].mint, symbol=pairs[address].symbol,
                tf=tf, start=start, at=self._seen, arms=sorted(names),
                features={**f.as_json(), "open": f.bar.open, "high": f.bar.high,
                          "low": f.bar.low, "close": f.bar.close}))

    # ==== the rolling rule ================================================================

    async def _catch(self, pairs: dict[str, MomPair], samples: dict[str, Sample],
                     live: Sequence[MomPosition], opened: dict[str, int]) -> None:
        arms = [a for a in ARMS if a.tf == "tick"]
        if not arms or not samples:
            return
        cool = self._seen - timedelta(seconds=arms[0].hold * arms[0].bar_seconds)
        recent = {(a, p) for a, p in (await self._s.execute(
            select(MomPosition.arm, MomPosition.pair_address)
            .where(MomPosition.arm.in_([a.name for a in arms]),
                   MomPosition.decided_at >= cool))).all()}
        holding = {(p.arm, p.pair_address) for p in live if p.status in LIVE}
        counts: dict[str, int] = defaultdict(int)
        for p in live:
            if p.status in LIVE:
                counts[p.arm] += 1
        signalled: dict[str, list[str]] = defaultdict(list)
        for address, s in samples.items():
            pair = pairs[address]
            if pair.status != "active" or s.row.liquidity is None \
                    or s.row.liquidity < config.MIN_LIQUIDITY_USD:
                continue
            roll = Rolling(
                change_m5=None if s.row.change_m5 is None else float(s.row.change_m5),
                volume_m5=None if s.row.volume_m5 is None else float(s.row.volume_m5),
                volume_h24=None if s.row.volume_h24 is None else float(s.row.volume_h24),
                buys_m5=s.row.buys_m5, sells_m5=s.row.sells_m5)
            ctx = Context(liquidity=float(s.row.liquidity),
                          age_days=(s.at - pair.born_at).total_seconds() / 86_400,
                          breadth=self._breadth)
            for arm in arms:
                if arm.rule is None or not fires_rolling(arm.rule, roll, ctx):
                    continue
                signalled[address].append(arm.name)
                key = (arm.name, address)
                if (key in holding or key in recent
                        or counts[arm.name] >= config.MAX_OPEN_PER_ARM):
                    continue
                change = Decimal(str(roll.change_m5)) / 100
                began = s.price / (1 + change) if change > -1 else s.price
                self._s.add(MomPosition(
                    arm=arm.name, pair_address=address, mint=pair.mint,
                    symbol=pair.symbol, dex_id=pair.dex_id, status="pending",
                    signal_tf="tick", signal_start=bucket(s.at, config.BASE_BAR_S),
                    signal_open=_q(began), signal_high=_q(max(began, s.price)),
                    signal_low=_q(min(began, s.price)), signal_close=_q(s.price),
                    features={"change_m5": roll.change_m5,
                              "vol_x": round(roll.volume_m5 / (roll.volume_h24 / 288), 2)
                              if roll.volume_m5 and roll.volume_h24 else None,
                              "buys": roll.buys_m5, "sells": roll.sells_m5,
                              "liquidity": float(s.row.liquidity)},
                    decided_at=s.fetched_at, notional_usd=config.TICKET_USD))
                holding.add(key)
                counts[arm.name] += 1
                opened[arm.name] += 1
        if not signalled:
            return
        # One radar row per pool per five-minute bucket, however many ticks
        # the move stays above the bar.
        keys = {address: bucket(samples[address].at, config.BASE_BAR_S)
                for address in signalled}
        seen = {(a, st) for a, st in (await self._s.execute(
            select(MomSignal.pair_address, MomSignal.start)
            .where(MomSignal.tf == "tick", MomSignal.pair_address.in_(list(keys)),
                   MomSignal.start >= min(keys.values())))).all()}
        for address, names in signalled.items():
            if (address, keys[address]) in seen:
                continue
            s = samples[address]
            self._s.add(MomSignal(
                pair_address=address, mint=pairs[address].mint,
                symbol=pairs[address].symbol, tf="tick", start=keys[address],
                at=s.fetched_at, arms=sorted(names),
                features={"change_m5": float(s.row.change_m5 or 0),
                          "close": float(s.price)}))

    # ==== housekeeping ======================================================================

    async def prune(self) -> dict[str, int]:
        candles = await self._s.execute(delete(MomCandle).where(
            MomCandle.start < self._now - timedelta(days=config.CANDLE_RETENTION_DAYS)))
        signals = await self._s.execute(delete(MomSignal).where(
            MomSignal.at < self._now - timedelta(days=config.SIGNAL_RETENTION_DAYS)))
        closes = await self._s.execute(delete(MomClose).where(
            MomClose.start < self._now - timedelta(days=config.SIGNAL_RETENTION_DAYS)))
        return {"candles": candles.rowcount or 0, "signals": signals.rowcount or 0,
                "closes": closes.rowcount or 0}

