"""The setup state machine, and the pass that records it every closed hour.

The top of this module is pure: given a score, a price and a resistance, what
state is this token in? The bottom is the engine that walks the universe,
computes levels and momentum through `data.py`, and writes `bo_levels`,
`bo_setup_snapshots` and `bo_episodes`.

**An episode is the unit of record.** It opens the first hour a token is worth
watching and closes when the question is answered — it broke out, it failed,
or it ran out of time. Its outcome columns are filled 72 hours later by a
separate pass, and that table is what a future phase will backtest. Nothing
here believes a setup will work; it only makes sure that when we find out, the
answer was written down before we knew it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.labs.breakout import config
from app.labs.breakout.candles import Candle
from app.labs.breakout.levels import Levels
from app.labs.breakout.levels import compute as compute_levels
from app.labs.breakout.models import BoEpisode, BoLevels, BoSetupSnapshot, BoUniverseMember
from app.labs.breakout.momentum import Momentum
from app.labs.breakout.momentum import score as compute_score

logger = get_logger(__name__)

WATCHING = "WATCHING"
PRE_BREAKOUT = "PRE_BREAKOUT"
BROKE_OUT = "BROKE_OUT"
FAILED = "FAILED"
NONE = "NONE"
#: States that keep an episode open, and the ones that close it.
OPEN_STATES = (WATCHING, PRE_BREAKOUT)
CLOSING_STATES = (BROKE_OUT, FAILED)
EXPIRED = "EXPIRED"
UNIVERSE_EXIT = "universe_exit"


@dataclass(frozen=True, slots=True)
class Evaluation:
    state: str
    #: How far below resistance the price is, in percent of resistance.
    #: NEGATIVE means above it. None when there is no resistance to measure to.
    distance_pct: float | None


def evaluate(
    score: int, price: float, resistance: float | None, *, had_pre_breakout: bool,
) -> Evaluation:
    """Which state this token is in, on one closed hourly bar.

    Order matters and is not arbitrary:

    1. No resistance above the close -> nothing to break, so `NONE`.
    2. A close more than `BREAK_CONFIRM_PCT` above resistance is `BROKE_OUT`,
       whatever the score says. The question this episode asked is answered.
    3. An episode that HAS reached `PRE_BREAKOUT` fails when price falls more
       than `FAIL_PCT` below resistance or the score drops under `FAIL_SCORE`.
       Checked before the entry states so a setup cannot re-arm on the same
       bar it fails. `FAIL_SCORE` is deliberately NOT `WATCH_SCORE`: the
       watch floor answers "is this worth looking at", this one answers "is
       this setup finished", and widening the first must not quietly make the
       trader hold losers longer.
    4. Then the two entry zones, tightest first.

    The band between resistance and `resistance * (1 + BREAK_CONFIRM_PCT)` is
    deliberately `NONE`: the brief puts `PRE_BREAKOUT` strictly below
    resistance and needs a 1% close above it to call a break, so a price
    inside that band is neither. It does not close an episode — a lull is not
    an answer.
    """
    if resistance is None or resistance <= 0:
        return Evaluation(NONE, None)

    distance_pct = (resistance - price) / resistance * 100.0
    if -distance_pct > config.BREAK_CONFIRM_PCT:
        return Evaluation(BROKE_OUT, distance_pct)
    if had_pre_breakout and (distance_pct > config.FAIL_PCT or score < config.FAIL_SCORE):
        return Evaluation(FAILED, distance_pct)
    if score >= config.PRE_SCORE and 0 <= distance_pct <= config.PRE_ZONE_PCT:
        return Evaluation(PRE_BREAKOUT, distance_pct)
    if score >= config.WATCH_SCORE and 0 <= distance_pct <= config.WATCH_ZONE_PCT:
        return Evaluation(WATCHING, distance_pct)
    return Evaluation(NONE, distance_pct)


def expired(opened_at: datetime, now: datetime,
            max_hours: int = config.MAX_EPISODE_HOURS) -> bool:
    return (now - opened_at) >= timedelta(hours=max_hours)


# --- the pass -----------------------------------------------------------------

class SetupEngine:
    """One pass over the active universe, on the newest closed hourly bar.

    Reads candles through `data.py` and writes only this lab's tables. It
    never opens a socket — a test parses the module to hold that — so a
    rate-limited candle pass cannot stop setups being evaluated on the bars
    that ARE stored.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def run(self, now: datetime) -> dict[str, Any]:
        from app.labs.breakout.data import get_candles, get_universe

        members = await get_universe(self._session)
        by_state: dict[str, int] = {}
        skipped = levels_written = snapshots = 0
        opened = closed = 0
        errors: list[str] = []

        active_mints = {m.mint for m in members}
        closed += await self.expire_departed(active_mints, now)

        for member in members:
            try:
                daily = await get_candles(self._session, member.mint, "day")
                levels = compute_levels(daily)
                if levels is None:
                    # Too young for a level. A skip, never an error.
                    skipped += 1
                    continue
                hourly = await get_candles(self._session, member.mint, "hour")
                bar_close = hourly[-1].close_time if hourly else None
                if bar_close is None:
                    # No hourly bar means no tick to evaluate ON. The daily
                    # levels are still worth storing.
                    await self.store_levels(member.mint, levels, now)
                    levels_written += 1
                    skipped += 1
                    continue

                price = float(hourly[-1].close)
                momentum = compute_score(levels, daily, hourly)
                await self.store_levels(member.mint, levels, now)
                levels_written += 1

                episode = await self.open_episode_for(member.mint)
                result = evaluate(
                    momentum.score, price, levels.nearest_resistance,
                    had_pre_breakout=bool(episode and episode.first_pre_breakout_at),
                )
                state = result.state
                if (episode is not None and state not in CLOSING_STATES
                        and expired(episode.opened_at, now)):
                    await self.close_episode(episode, now, EXPIRED)
                    closed += 1
                    episode = None

                by_state[state] = by_state.get(state, 0) + 1
                if state == NONE and episode is None:
                    continue

                if state != NONE:
                    await self.store_snapshot(member, state, momentum, price, levels,
                                              result.distance_pct, bar_close, now)
                    snapshots += 1

                if state in OPEN_STATES:
                    if episode is None:
                        await self.open_episode(member, state, price, levels, now)
                        opened += 1
                    else:
                        await self.advance_episode(episode, state, price, now)
                elif state in CLOSING_STATES and episode is not None:
                    await self.advance_episode(episode, state, price, now)
                    await self.close_episode(episode, now, state)
                    closed += 1
                elif episode is not None:
                    # NONE with an episode open: a lull. Keep tracking the
                    # extremes so the outcome columns stay honest.
                    await self.advance_episode(episode, state, price, now)
            except Exception as exc:  # containment, per token
                logger.warning("breakout_setup_failed", mint=member.mint, error=repr(exc))
                errors.append(f"{member.mint}: {exc!r}")

        logger.info("breakout_setups_evaluated", tokens=len(members), skipped=skipped,
                    by_state=by_state, opened=opened, closed=closed)
        return {"phase": "setups", "tokens": len(members), "skipped": skipped,
                "levels": levels_written, "snapshots": snapshots,
                "by_state": by_state, "episodes_opened": opened,
                "episodes_closed": closed, "errors": errors}

    # --- levels -------------------------------------------------------------

    async def store_levels(self, mint: str, levels: Levels, now: datetime) -> None:
        """Latest per token — one row, replaced each pass."""
        stmt = pg_insert(BoLevels).values(
            mint=mint,
            clusters=[c.as_dict() for c in levels.clusters],
            nearest_resistance=_dec(levels.nearest_resistance),
            atr=_dec(levels.atr), atr_fast=_dec(levels.atr_fast),
            atr_slow=_dec(levels.atr_slow),
            volume_mean=_dec(levels.volume_mean),
            high_range=_dec(levels.high_range), low_range=_dec(levels.low_range),
            close=_dec(levels.close), daily_bars=levels.bars, computed_at=now,
        )
        await self._session.execute(stmt.on_conflict_do_update(
            constraint="uq_bo_levels_mint",
            set_={k: getattr(stmt.excluded, k) for k in (
                "clusters", "nearest_resistance", "atr", "atr_fast", "atr_slow",
                "volume_mean", "high_range", "low_range", "close", "daily_bars",
                "computed_at")},
        ))

    # --- snapshots ----------------------------------------------------------

    async def store_snapshot(
        self, member: BoUniverseMember, state: str, momentum: Momentum, price: float,
        levels: Levels, distance_pct: float | None, bar_close: datetime, now: datetime,
    ) -> None:
        """One row per token per hourly bar in a non-NONE state. Keyed on the
        BAR, not on the clock, so re-running a pass rewrites rather than
        duplicates."""
        stmt = pg_insert(BoSetupSnapshot).values(
            mint=member.mint, bar_close_time=bar_close, state=state,
            score=momentum.score, components=momentum.components(),
            price=_dec(price), resistance=_dec(levels.nearest_resistance),
            distance_pct=_dec(distance_pct),
            hourly_missing=momentum.hourly_missing, computed_at=now,
        )
        await self._session.execute(stmt.on_conflict_do_update(
            constraint="uq_bo_setup_snapshots_mint_bar",
            set_={k: getattr(stmt.excluded, k) for k in (
                "state", "score", "components", "price", "resistance",
                "distance_pct", "hourly_missing", "computed_at")},
        ))

    # --- episodes -----------------------------------------------------------

    async def open_episode_for(self, mint: str) -> BoEpisode | None:
        return (await self._session.execute(
            select(BoEpisode).where(BoEpisode.mint == mint,
                                    BoEpisode.closed_at.is_(None))
        )).scalar_one_or_none()

    async def open_episode(self, member: BoUniverseMember, state: str, price: float,
                           levels: Levels, now: datetime) -> None:
        pre = state == PRE_BREAKOUT
        self._session.add(BoEpisode(
            mint=member.mint, opened_at=now,
            first_pre_breakout_at=now if pre else None,
            entry_ref_price=_dec(price) if pre else None,
            resistance_at_open=_dec(levels.nearest_resistance),
            peak_price=_dec(price) if pre else None,
            min_price=_dec(price) if pre else None,
        ))
        await self._session.flush()

    async def advance_episode(self, episode: BoEpisode, state: str, price: float,
                              now: datetime) -> None:
        """Record the first PRE_BREAKOUT and, once there is a reference price,
        the extremes since. `peak_price`/`min_price` are tracked ONLY after
        the reference exists — a high reached before we would have bought is
        not a gain we would have had."""
        values: dict[str, Any] = {}
        if state == PRE_BREAKOUT and episode.first_pre_breakout_at is None:
            values |= {"first_pre_breakout_at": now, "entry_ref_price": _dec(price),
                       "peak_price": _dec(price), "min_price": _dec(price)}
        elif episode.first_pre_breakout_at is not None:
            mark = _dec(price)
            if episode.peak_price is None or mark > episode.peak_price:
                values["peak_price"] = mark
            if episode.min_price is None or mark < episode.min_price:
                values["min_price"] = mark
        if values:
            await self._session.execute(
                update(BoEpisode).where(BoEpisode.id == episode.id).values(**values))
            for key, value in values.items():
                setattr(episode, key, value)

    async def close_episode(self, episode: BoEpisode, now: datetime, reason: str) -> None:
        await self._session.execute(
            update(BoEpisode).where(BoEpisode.id == episode.id, BoEpisode.closed_at.is_(None))
            .values(closed_at=now, close_reason=reason))
        episode.closed_at, episode.close_reason = now, reason
        logger.info("breakout_episode_closed", mint=episode.mint, reason=reason)

    async def expire_departed(self, active: set[str], now: datetime) -> int:
        """A token that left the universe cannot answer its own question. Its
        episode EXPIRES with reason `universe_exit` — pre-decided."""
        stale = (await self._session.execute(
            select(BoEpisode).where(BoEpisode.closed_at.is_(None),
                                    BoEpisode.mint.not_in(active) if active else True)
        )).scalars().all()
        for episode in stale:
            await self.close_episode(episode, now, UNIVERSE_EXIT)
        return len(stale)


def _dec(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


# --- outcomes -----------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class TrailResult:
    """What a fixed-notional position with a trailing stop would have done."""

    result_pct: float
    gappy: bool


def trail_result(
    bars: Sequence[Candle], entry: float, *, notional: float | None = None,
    trail_usd: float | None = None, interval_hours: int = 1,
) -> TrailResult:
    """A `notional` position opened at `entry` and closed when its value falls
    `trail_usd` below its high-water value. Returns the percent result.

    The per-bar rule is `rules.trail_step`, the same function the live trader
    calls once per tick: the low before the high, and the high-water mark
    raised only after the low has been checked. See its docstring for why
    that ordering is the line that decides whether these numbers mean
    anything.

    `gappy` is set when the bars are not contiguous at `interval_hours`. A gap
    is treated as no movement (the pre-decided rule), which understates both
    directions; the flag is there so the number can be excluded later rather
    than silently trusted.
    """
    from app.labs.breakout.rules import trail_step

    # Read at call time, not bound as defaults — see `rules.py`.
    notional = config.TRAIL_NOTIONAL_USD if notional is None else notional
    trail_usd = config.TRAIL_USD if trail_usd is None else trail_usd
    if entry <= 0 or not bars:
        return TrailResult(0.0, True)

    qty = notional / entry
    high_water = notional
    gappy = False
    previous: Candle | None = None

    for bar in bars:
        if previous is not None:
            elapsed = (bar.open_time - previous.open_time).total_seconds() / 3600.0
            if abs(elapsed - interval_hours) > 1e-6:
                gappy = True
        previous = bar

        # The SAME function the live trader calls once per tick. Folded here,
        # called singly there — one rule, not two implementations to keep in
        # step. `test_consistency.py` asserts the two agree end to end.
        step = trail_step(qty=qty, low=float(bar.low), high=float(bar.high),
                          high_water=high_water, trail=trail_usd)
        if step.stopped:
            return TrailResult((step.exit_value - notional) / notional * 100.0, gappy)
        high_water = step.high_water

    final = qty * float(bars[-1].close)
    return TrailResult((final - notional) / notional * 100.0, gappy)


def pct_change(entry: float, later: float | None) -> float | None:
    if entry <= 0 or later is None:
        return None
    return (later - entry) / entry * 100.0


def price_at(bars: Sequence[Candle], when: datetime) -> float | None:
    """The close of the last bar that had closed by `when`, or None."""
    eligible = [b for b in bars if b.close_time <= when]
    return float(eligible[-1].close) if eligible else None


class OutcomeEngine:
    """Fills the outcome columns of episodes whose 72-hour window has passed.

    Runs daily, reads only stored hourly bars, and never touches an episode
    twice — `outcome_at` is the marker.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def run(self, now: datetime) -> dict[str, Any]:
        from app.labs.breakout.data import get_candles

        cutoff = now - timedelta(hours=config.OUTCOME_WINDOW_HOURS)
        episodes = (await self._session.execute(
            select(BoEpisode).where(
                BoEpisode.closed_at.is_not(None),
                BoEpisode.outcome_at.is_(None),
                BoEpisode.first_pre_breakout_at.is_not(None),
                BoEpisode.first_pre_breakout_at <= cutoff,
            )
        )).scalars().all()

        filled = skipped = 0
        for episode in episodes:
            entry = float(episode.entry_ref_price or 0)
            start = episode.first_pre_breakout_at
            if entry <= 0 or start is None:
                skipped += 1
                continue
            bars = [b for b in await get_candles(self._session, episode.mint, "hour")
                    if b.open_time >= start]
            if not bars:
                # No stored bars in the window — mark it done and gappy rather
                # than retry for ever.
                await self._write(episode, now, gappy=True)
                filled += 1
                continue
            trail = trail_result(bars, entry)
            highs = [float(b.high) for b in bars]
            lows = [float(b.low) for b in bars]
            await self._write(
                episode, now, gappy=trail.gappy,
                max_gain=pct_change(entry, max(highs)),
                max_loss=pct_change(entry, min(lows)),
                at_24h=pct_change(entry, price_at(bars, start + timedelta(hours=24))),
                at_72h=pct_change(entry, price_at(bars, start + timedelta(hours=72))),
                trail25=trail.result_pct,
            )
            filled += 1

        logger.info("breakout_outcomes", filled=filled, skipped=skipped)
        return {"phase": "outcomes", "filled": filled, "skipped": skipped}

    async def _write(self, episode: BoEpisode, now: datetime, *, gappy: bool,
                     max_gain: float | None = None, max_loss: float | None = None,
                     at_24h: float | None = None, at_72h: float | None = None,
                     trail25: float | None = None) -> None:
        await self._session.execute(
            update(BoEpisode).where(BoEpisode.id == episode.id).values(
                max_gain_pct_from_ref=_dec(max_gain),
                max_loss_pct_from_ref=_dec(max_loss),
                pct_at_24h=_dec(at_24h), pct_at_72h=_dec(at_72h),
                trail25_result_pct=_dec(trail25), outcome_gappy=gappy,
                outcome_at=now,
            ))


def utcnow() -> datetime:
    return datetime.now(UTC)
