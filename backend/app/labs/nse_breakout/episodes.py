"""The engine: bars in, states and episodes out.

Two callers, one fold. `walk()` runs a symbol's bars through
`states.evaluate` / `states.advance`; the live pass walks only the newest bar,
the replay walks every bar from the start. They call the same function with
different slices, which is the only thing that makes the replayed statistics a
claim about the live rules rather than about a second implementation.

Outcomes are filled by a SEPARATE pass once the window has elapsed
(`outcomes.py` does the arithmetic, `OutcomeFiller` below does the writing).
Nothing that decides a state can see a return.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Interval, delete, literal, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.labs.nse_breakout import config, outcomes, states
from app.labs.nse_breakout import levels as levels_mod
from app.labs.nse_breakout import score as score_mod
from app.labs.nse_breakout.models import (
    BtCandle,
    BtEpisode,
    BtEpisodeEvent,
    BtIndexClose,
    BtRun,
    BtState,
    BtUniverseMember,
)

logger = get_logger(__name__)

LIVE = "live"
REPLAY = "replay"

#: Columns `walk` produces for an episode, and the only ones it may write.
EPISODE_FIELDS = (
    "opened", "first_near_date", "ref_price", "resistance", "score_at_open",
    "max_score", "breakout_date", "breakout_price", "breakout_volume_mult",
    "days_to_breakout", "state", "bars_open", "bars_since_breakout",
    "weak_bars", "closed", "close_reason",
)


def _dec(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(round(value, 4)))


@dataclass(slots=True)
class Walk:
    """What one symbol's walk produced, before anything is written.

    `current` is the episode that is open at the end of the walk, or the one
    that closed during it — `is_new` says whether the walk opened it or
    inherited it from the database.
    """

    opened: list[dict[str, Any]]
    events: list[dict[str, Any]]
    current: dict[str, Any] | None
    snapshot: dict[str, Any] | None


def walk(symbol: str, bars: Sequence[BtCandle], *, start_index: int,
         opening: states.EpisodeState | None = None,
         seed: dict[str, Any] | None = None) -> Walk:
    """Fold the state machine over `bars[start_index:]`.

    `bars` must be OLDEST FIRST and must include the whole history before
    `start_index`: the levels for bar `i` are computed from `bars[:i+1]`, never
    from a window. A level is a level because of where the stock has been, and
    truncating the history would change it.
    """
    episode = opening or states.EpisodeState()
    open_row: dict[str, Any] | None = _row_from(symbol, episode, seed) \
        if episode.is_open else None
    is_new = False
    opened: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    snapshot: dict[str, Any] | None = None

    for i in range(start_index, len(bars)):
        prefix = bars[:i + 1]
        level_read = levels_mod.compute(prefix)
        if level_read is None:
            continue
        reading = score_mod.compute(prefix, level_read)
        was_open, was_state = episode.is_open, episode.state
        evaluation = states.evaluate(level_read, reading.score, episode)
        episode = states.advance(episode, evaluation, prefix[-1].date,
                                 level_read.close)

        if episode.is_open and not was_open:
            open_row = _row_from(symbol, episode, {"id": uuid.uuid4()})
            open_row["score_at_open"] = reading.score
            open_row["max_score"] = reading.score
            is_new = True
            opened.append(open_row)
        elif open_row is not None:
            _refresh(open_row, episode, reading.score, evaluation)

        if open_row is not None and (evaluation.state != was_state or not was_open):
            events.append({"id": uuid.uuid4(), "episode_id": open_row["id"],
                           "date": prefix[-1].date, "state": evaluation.state,
                           "close": _dec(level_read.close),
                           "resistance": _dec(evaluation.resistance),
                           "score": reading.score, "note": evaluation.reason})

        if evaluation.closes_episode and open_row is not None:
            open_row["closed"] = prefix[-1].date
            open_row["close_reason"] = evaluation.reason or evaluation.state
            if is_new:
                open_row, is_new = None, False
            episode = states.EpisodeState(weak_bars=episode.weak_bars)

        if i == len(bars) - 1:
            snapshot = _snapshot(symbol, level_read, reading, evaluation,
                                 prefix[-1].date)
    return Walk(opened=opened, events=events,
                current=None if is_new else open_row, snapshot=snapshot)


def _row_from(symbol: str, episode: states.EpisodeState,
              seed: dict[str, Any] | None) -> dict[str, Any]:
    """A fresh row, or the stored one's columns that the walk does not own.

    `score_at_open` and the breakout facts are written ONCE and must survive
    every later pass. Seeding them from the database rather than defaulting
    them is the difference between updating an episode and flattening it.
    """
    seed = seed or {}
    row = {"id": seed.get("id"), "symbol": symbol, "opened": episode.opened,
            "first_near_date": episode.first_near_date,
            "ref_price": _dec(episode.ref_price),
            "resistance": _dec(episode.resistance), "score_at_open": 0,
            "max_score": 0, "breakout_date": episode.breakout_date,
            "breakout_price": _dec(episode.breakout_price),
            "breakout_volume_mult": None, "days_to_breakout": None,
            "state": episode.state, "bars_open": episode.bars_open,
            "bars_since_breakout": episode.bars_since_breakout,
            "weak_bars": episode.weak_bars, "closed": None, "close_reason": None}
    for field in ("score_at_open", "max_score", "breakout_volume_mult",
                  "days_to_breakout"):
        if seed.get(field) is not None:
            row[field] = seed[field]
    return row


def _refresh(row: dict[str, Any], episode: states.EpisodeState, score: int,
             evaluation: states.Evaluation) -> None:
    """Carry the ADVANCED EPISODE's state onto its row, not the bar's.

    They differ on a NONE bar: the episode stays NEAR (or WATCH, or BREAKOUT)
    while today's evaluation says nothing happened. Writing the bar's state
    here would store `NONE` on an open episode, and tomorrow's pass — which
    rebuilds its starting point from this row — would read that as "not open",
    abandon the episode mid-flight and open a second one when it recovered.
    The bar's own state belongs in the snapshot and the event, which is where
    it goes.
    """
    row["state"] = episode.state
    row["max_score"] = max(row["max_score"], score)
    row["first_near_date"] = episode.first_near_date
    row["ref_price"] = _dec(episode.ref_price)
    row["resistance"] = _dec(episode.resistance)
    row["bars_open"] = episode.bars_open
    row["bars_since_breakout"] = episode.bars_since_breakout
    row["weak_bars"] = episode.weak_bars
    if episode.breakout_date is not None and row["breakout_date"] is None:
        row["breakout_date"] = episode.breakout_date
        row["breakout_price"] = _dec(episode.breakout_price)
        row["breakout_volume_mult"] = _dec(evaluation.volume_mult)
        row["days_to_breakout"] = episode.bars_open


def _snapshot(symbol: str, level_read: levels_mod.Levels,
              reading: score_mod.Score, evaluation: states.Evaluation,
              when: date) -> dict[str, Any]:
    return {
        "symbol": symbol, "bar_date": when, "state": evaluation.state,
        "score": reading.score, "components": reading.components(),
        "close": _dec(level_read.close),
        "resistance": _dec(evaluation.resistance
                           if evaluation.resistance is not None
                           else level_read.nearest_resistance),
        "distance_pct": _dec(level_read.distance_pct),
        "range_pct": _dec(level_read.range_pct),
        "tightness": level_read.tightness, "is_52w_high": level_read.is_52w_high,
        "week52_high": _dec(level_read.week52_high), "atr": _dec(level_read.atr),
        "volume_mult": _dec(level_read.volume_mult),
        "clusters": [c.as_dict() for c in level_read.clusters],
        "bars": level_read.bars,
    }


def seed_of(episode: BtEpisode | None) -> dict[str, Any] | None:
    """The columns the walk must not invent for an episode it inherited."""
    if episode is None:
        return None
    return {"id": episode.id, "score_at_open": episode.score_at_open,
            "max_score": episode.max_score,
            "breakout_volume_mult": episode.breakout_volume_mult,
            "days_to_breakout": episode.days_to_breakout}


def state_of(episode: BtEpisode | None) -> states.EpisodeState | None:
    """The ORM row as the value the machine folds over."""
    if episode is None:
        return None
    return states.EpisodeState(
        opened=episode.opened, state=episode.state,
        first_near_date=episode.first_near_date,
        ref_price=float(episode.ref_price) if episode.ref_price is not None else None,
        resistance=float(episode.resistance)
        if episode.resistance is not None else None,
        breakout_date=episode.breakout_date,
        breakout_price=float(episode.breakout_price)
        if episode.breakout_price is not None else None,
        bars_open=episode.bars_open,
        bars_since_breakout=episode.bars_since_breakout,
        weak_bars=episode.weak_bars)


class Detector:
    """Runs the walk against the database and writes what it found."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def bars(self, symbol: str) -> list[BtCandle]:
        return list((await self._session.execute(
            select(BtCandle).where(BtCandle.symbol == symbol)
            .order_by(BtCandle.date))).scalars())

    async def _scorable(self) -> list[str]:
        return list((await self._session.execute(
            select(BtUniverseMember.symbol)
            .where(BtUniverseMember.active.is_(True),
                   BtUniverseMember.bars >= config.MIN_BARS_FOR_LEVELS)
            .order_by(BtUniverseMember.symbol))).scalars())

    async def daily(self, *, now: datetime | None = None) -> dict[str, Any]:
        """One pass over the scorable universe, evaluating the newest bar only.

        The whole history is loaded per symbol because a bar's levels come from
        everything before it; only the last bar is EVALUATED, which is what
        makes this a daily pass rather than a replay.
        """
        now = now or datetime.now(UTC)
        started = now
        open_rows = {e.symbol: e for e in (await self._session.execute(
            select(BtEpisode).where(BtEpisode.source == LIVE,
                                    BtEpisode.closed.is_(None)))).scalars()}
        counts: dict[str, int] = {}
        snapshots: list[dict[str, Any]] = []
        scanned = 0
        for symbol in await self._scorable():
            bars = await self.bars(symbol)
            if len(bars) < config.MIN_BARS_FOR_LEVELS:
                continue
            existing = open_rows.get(symbol)
            result = walk(symbol, bars, start_index=len(bars) - 1,
                          opening=state_of(existing), seed=seed_of(existing))
            scanned += 1
            if result.snapshot is not None:
                snapshots.append(result.snapshot)
                counts[result.snapshot["state"]] = counts.get(
                    result.snapshot["state"], 0) + 1
            if result.current is not None and existing is not None:
                for field in EPISODE_FIELDS:
                    setattr(existing, field, result.current[field])
            for row in result.opened:
                self._session.add(BtEpisode(source=LIVE, created_at=now, **row))
            for event in result.events:
                self._session.add(BtEpisodeEvent(**event))
        await self._upsert_states(snapshots, now)
        # A name that left the universe keeps its episodes — that is the
        # record — but not its state row: `/stock` would otherwise show a
        # stale score against a current-looking bar date.
        dropped = await self._session.execute(
            delete(BtState).where(BtState.symbol.in_(
                select(BtUniverseMember.symbol)
                .where(BtUniverseMember.active.is_(False)))))

        self._session.add(BtRun(
            phase="levels", started_at=started, finished_at=datetime.now(UTC),
            symbols=scanned, rows=len(snapshots),
            detail={"states": counts, "dropped_states": dropped.rowcount or 0}))
        logger.info("nse_states_evaluated", symbols=scanned, states=counts)
        return {"phase": "levels", "symbols": scanned, "states": counts}

    async def replay(self, *, limit: int = config.REPLAY_SYMBOLS_PER_RUN,
                     now: datetime | None = None) -> dict[str, Any]:
        """The honest test: the same machine walked causally over the whole
        history, writing episodes flagged `replay`.

        Resumable and deadline-bounded like the backfill, for the same reason —
        a pass killed by the worker's soft limit commits nothing. The marker is
        `bt_universe.replayed_at`, not the presence of episodes: a symbol that
        produced none has still been replayed, and counting episodes would walk
        it again on every pass for ever.
        """
        now = now or datetime.now(UTC)
        started = now
        pending = list((await self._session.execute(
            select(BtUniverseMember.symbol)
            .where(BtUniverseMember.active.is_(True),
                   BtUniverseMember.bars >= config.MIN_BARS_FOR_LEVELS,
                   BtUniverseMember.replayed_at.is_(None))
            .order_by(BtUniverseMember.symbol))).scalars())

        deadline = time.monotonic() + config.REPLAY_DEADLINE_SECONDS
        walked = written = 0
        for symbol in pending[:limit]:
            if time.monotonic() >= deadline:
                break
            bars = await self.bars(symbol)
            if len(bars) >= config.MIN_BARS_FOR_LEVELS:
                result = walk(symbol, bars,
                              start_index=config.MIN_BARS_FOR_LEVELS - 1)
                # Every episode the replay produced is in `opened` — it starts
                # from nothing, so there is never an inherited `current`.
                for row in result.opened:
                    self._session.add(BtEpisode(source=REPLAY, created_at=now,
                                                **row))
                for event in result.events:
                    self._session.add(BtEpisodeEvent(**event))
                written += len(result.opened)
            await self._session.execute(
                update(BtUniverseMember)
                .where(BtUniverseMember.symbol == symbol)
                .values(replayed_at=now))
            walked += 1

        remaining = len(pending) - walked
        self._session.add(BtRun(
            phase="replay", started_at=started, finished_at=datetime.now(UTC),
            symbols=walked, rows=written, detail={"remaining": remaining}))
        logger.info("nse_replay_pass", symbols=walked, episodes=written,
                    remaining=remaining)
        return {"phase": "replay", "symbols": walked, "episodes": written,
                "remaining": remaining}

    async def _upsert_states(self, snapshots: list[dict[str, Any]],
                             now: datetime) -> None:
        if not snapshots:
            return
        previous = {s: (state, days) for s, state, days in (
            await self._session.execute(
                select(BtState.symbol, BtState.state,
                       BtState.days_in_state))).all()}
        for row in snapshots:
            was = previous.get(row["symbol"])
            row["days_in_state"] = was[1] + 1 if was and was[0] == row["state"] else 1
            row["updated_at"] = now
        for start in range(0, len(snapshots), 500):
            chunk = snapshots[start:start + 500]
            stmt = pg_insert(BtState).values(chunk)
            await self._session.execute(stmt.on_conflict_do_update(
                constraint="uq_bt_states_symbol",
                set_={k: getattr(stmt.excluded, k) for k in chunk[0]
                      if k != "symbol"}))


class OutcomeFiller:
    """Fills the outcome columns once the window has elapsed.

    **A separate pass on purpose.** Nothing that decides a state may see a
    return, so the columns that say what happened are written by code that
    never touches `states.evaluate`. That separation is the only reason the
    replayed statistics are a backtest rather than a description.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def fill(self, *, limit: int = config.OUTCOME_SYMBOLS_PER_RUN,
                   now: datetime | None = None) -> dict[str, Any]:
        """Fill every fillable episode, **one symbol at a time**.

        Batched by symbol rather than by episode: a pass over the whole replay
        touches ~1,300 symbols with ~600 bars each, and loading all of those at
        once to fill 9,000 episodes would hold the entire candle table in
        memory for the sake of a few arithmetic passes.
        """
        now = now or datetime.now(UTC)
        started = now
        # Only symbols that can have something fillable. An episode measured
        # 10 bars before the end of the data will never fill until more bars
        # arrive, and without this pre-filter those symbols sit at the front of
        # the ordering re-failing on every pass and STARVING every symbol after
        # the limit.
        #
        # The span is exactly the MINIMUM calendar window 40 trading days can
        # occupy (eight whole weeks). Anything shorter certainly cannot hold 40
        # sessions, so excluding it is sound; anything longer is a candidate
        # and `_fill_one` does the exact check.
        #
        # `literal(..., Interval())` and not a bare timedelta: SQLAlchemy types
        # a bind from the LEFT operand, so `last_seen - timedelta(...)` sends
        # the timedelta as a DATE. That statement compiles, runs, raises
        # nothing — and silently matches no rows, while the identical
        # arithmetic in Python agrees with you the whole time.
        gap = literal(timedelta(days=config.OUTCOME_MAX_HORIZON * 7 // 5),
                      Interval())
        symbols = list((await self._session.execute(
            select(BtEpisode.symbol)
            .join(BtUniverseMember, BtUniverseMember.symbol == BtEpisode.symbol)
            .where(BtEpisode.outcomes_filled_at.is_(None),
                   BtEpisode.first_near_date.is_not(None),
                   BtEpisode.first_near_date <= BtUniverseMember.last_seen - gap)
            .group_by(BtEpisode.symbol).order_by(BtEpisode.symbol)
            .limit(limit))).scalars())
        if not symbols:
            return {"phase": "outcomes", "filled": 0, "waiting": 0, "symbols": 0}

        index = {d: float(c) for d, c in (await self._session.execute(
            select(BtIndexClose.date, BtIndexClose.close)
            .where(BtIndexClose.index_name == config.NIFTY_NAME))).all()}

        deadline = time.monotonic() + config.OUTCOME_DEADLINE_SECONDS
        filled = waiting = done_symbols = 0
        for symbol in symbols:
            if time.monotonic() >= deadline:
                break
            bars = list((await self._session.execute(
                select(BtCandle).where(BtCandle.symbol == symbol)
                .order_by(BtCandle.date))).scalars())
            pending = list((await self._session.execute(
                select(BtEpisode).where(
                    BtEpisode.symbol == symbol,
                    BtEpisode.outcomes_filled_at.is_(None)))).scalars())
            for episode in pending:
                if self._fill_one(episode, bars, index, now):
                    filled += 1
                else:
                    waiting += 1
            done_symbols += 1

        self._session.add(BtRun(
            phase="outcomes", started_at=started, finished_at=datetime.now(UTC),
            rows=filled, symbols=done_symbols,
            detail={"waiting": waiting, "remaining_symbols":
                    len(symbols) - done_symbols}))
        logger.info("nse_outcomes_filled", filled=filled, waiting=waiting,
                    symbols=done_symbols)
        return {"phase": "outcomes", "filled": filled, "waiting": waiting,
                "symbols": done_symbols,
                "remaining_symbols": len(symbols) - done_symbols}

    def _fill_one(self, episode: BtEpisode, bars: Sequence[BtCandle],
                  index: dict[date, float], now: datetime) -> bool:
        """True when the episode's windows were complete and it was filled.

        Returns False — and writes NOTHING — while a window is still open. A
        half-filled row would be read as a result.
        """
        ref_from = self._forward(bars, episode.first_near_date)
        bo_from = self._forward(bars, episode.breakout_date)
        horizon = config.OUTCOME_MAX_HORIZON
        if ref_from is None or len(ref_from) < horizon:
            return False
        if episode.breakout_date is not None and (
                bo_from is None or len(bo_from) < horizon):
            return False

        ref_price = float(episode.ref_price) if episode.ref_price else 0.0
        ref = outcomes.returns_from(ref_price, ref_from)
        for n in config.OUTCOME_HORIZONS:
            setattr(episode, f"ret_ref_{n}", _dec(ref.get(n)))
        episode.mfe_20 = _dec(ref.mfe)
        episode.mae_20 = _dec(ref.mae)
        episode.rel_nifty_20 = _dec(outcomes.relative_to_index(
            ref.get(config.OUTCOME_WINDOW_DAYS),
            self._index_window(index, episode.first_near_date, bars),
            config.OUTCOME_WINDOW_DAYS))

        if episode.breakout_date is not None and bo_from is not None:
            entry = float(episode.breakout_price) if episode.breakout_price else 0.0
            bo = outcomes.returns_from(entry, bo_from)
            for n in config.OUTCOME_HORIZONS:
                setattr(episode, f"ret_bo_{n}", _dec(bo.get(n)))
            episode.mfe_bo_20 = _dec(bo.mfe)
            episode.mae_bo_20 = _dec(bo.mae)
            episode.held_20d_pct = _dec(bo.get(config.OUTCOME_WINDOW_DAYS))
            trail = outcomes.trail_result(entry, bo_from)
            if trail is not None:
                episode.trail10_pct = _dec(trail.pct)
                episode.trail10_bars = trail.bars_held
                episode.trail10_stopped = trail.stopped
            episode.rel_nifty_bo_20 = _dec(outcomes.relative_to_index(
                bo.get(config.OUTCOME_WINDOW_DAYS),
                self._index_window(index, episode.breakout_date, bars),
                config.OUTCOME_WINDOW_DAYS))

        episode.outcomes_filled_at = now
        return True

    @staticmethod
    def _forward(bars: Sequence[BtCandle], when: date | None,
                 ) -> list[BtCandle] | None:
        """The bars strictly after `when`, oldest first."""
        if when is None:
            return None
        return [b for b in bars if b.date > when]

    @staticmethod
    def _index_window(index: dict[date, float], when: date | None,
                      bars: Sequence[BtCandle]) -> list[float]:
        """Nifty closes on the stock's OWN trading days, starting at `when`.

        Aligned to the stock's bars rather than to the index's own calendar, so
        the two returns cover the same sessions. A day the index is missing
        breaks the alignment, so the window stops there and
        `relative_to_index` returns null — pre-decided: null, never zero.
        """
        if when is None:
            return []
        window: list[float] = []
        for bar in bars:
            if bar.date < when:
                continue
            close = index.get(bar.date)
            if close is None:
                break
            window.append(close)
            if len(window) > config.OUTCOME_WINDOW_DAYS:
                break
        return window
