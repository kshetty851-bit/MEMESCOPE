"""Meme Lifecycle Lab — the point-in-time replay.

Drives decision instants in order and, at each instant ``T``, sees only what
``pit.information_available_at`` admits at ``T``:

  1. per meme (sorted by id): InformationState → attention features → market
     features per visible linked mint → events (accumulated per meme and fed
     back as ``prior_events``) → lifecycle state
  2. exits for open positions, over the market readings that became available
     since the position's last evaluation, in time order (``exits.py``)
  3. entries per meme per visible linked mint (sorted): divergence → strategy
     decision → portfolio entry at the **latest market price visible at T**

Exits run before entries at the same instant. Both use only information known
at ``T``, and a slot released by a position that closed on a reading
available at ``T`` is genuinely free at ``T``; doing entries first would make
capacity depend on loop order rather than on what was known.

Look-ahead guards, in depth:

* The PIT gate is the only admission point for features and decisions.
* Before calling it, this module slices each meme's rows by a *lower bound* of
  their knowledge time (``retrieved_at``, or for EXPLORATORY backfill
  ``source_timestamp/observed_at + PUBLICATION_LAG``), so a future row is never
  even handed to the gate. AUTHORITATIVE drops BACKFILL rows up front.
* Entry prices and exit readings come from the market index here, gated on
  ``available_at <= T`` — never a later reading.

Positions still open when the data runs out are labelled ``END_OF_DATA``, not
filled, and excluded from closed-trade metrics.

Cost: O(ticks * memes) calls into the engines. Inputs are pre-sorted and
pre-partitioned per meme and per mint once; each instant takes a bisect slice
(no rescans of other memes' rows), exits advance a per-position cursor, and the
latest-price lookup is O(log n) via a prefix index. What remains is the
engines' own per-state cost; ``history_lookback`` bounds it when needed.

Pure: no I/O, no clock, no randomness. Inputs are canonically sorted, so the
input order does not matter, and ``input_fingerprint`` identifies them.
"""

from __future__ import annotations

import hashlib
import json
from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.lifecycle_lab import attention as attention_engine
from app.lifecycle_lab import divergence as divergence_engine
from app.lifecycle_lab import events as events_engine
from app.lifecycle_lab import market as market_engine
from app.lifecycle_lab import pit, strategy
from app.lifecycle_lab import states as states_engine
from app.lifecycle_lab.config import LabConfig
from app.lifecycle_lab.domain import (
    ACCUMULATING_METRICS,
    PUBLICATION_LAG,
    AgeBucket,
    Arm,
    AttentionFeatures,
    CollectionRun,
    DataClass,
    DivergenceCase,
    InformationState,
    LifecycleState,
    MarketFeatures,
    MarketPoint,
    Measured,
    Meme,
    MemeAlias,
    MemeEvent,
    MemeTokenLink,
    Observation,
    ResearchMode,
    TokenInfo,
    Unavailable,
    spec_hash,
)
from app.lifecycle_lab.exits import (
    PositionExitState,
    evaluate_attention_collapse,
    evaluate_exit,
)
from app.lifecycle_lab.metrics import LabMetrics, compute_metrics
from app.lifecycle_lab.portfolio import (
    EntryRequest,
    PaperTrade,
    Portfolio,
    PortfolioSnapshot,
    Rejection,
)

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
#: Most-recent events copied onto a trade's evidence timeline.
MAX_TIMELINE_EVENTS = 20
_MIN_TIME = datetime.min.replace(tzinfo=UTC)


# --------------------------------------------------------------------------
# Inputs / outputs
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReplayInputs:
    memes: tuple[Meme, ...]
    aliases: tuple[MemeAlias, ...] = ()
    links: tuple[MemeTokenLink, ...] = ()
    tokens: tuple[TokenInfo, ...] = ()
    observations: tuple[Observation, ...] = ()
    market: tuple[MarketPoint, ...] = ()
    runs: tuple[CollectionRun, ...] = ()


@dataclass(frozen=True, slots=True)
class ReplayResult:
    mode: ResearchMode
    arm: Arm
    start: datetime
    end: datetime
    hindsight_links: bool
    contains_backfill: bool
    input_fingerprint: str
    ticks: int
    #: Closed trades and END_OF_DATA positions, by (entry_at, trade_key).
    trades: tuple[PaperTrade, ...]
    snapshots: tuple[PortfolioSnapshot, ...]
    events: tuple[MemeEvent, ...]
    #: Run-length decision log: one row per (meme, mint) outcome run.
    decisions: tuple[dict[str, Any], ...]
    rejection_counts: dict[str, int]
    metrics: LabMetrics
    open_at_end: tuple[PaperTrade, ...] = field(default=())

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "arm": self.arm.value,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "hindsight_links": self.hindsight_links,
            "contains_backfill": self.contains_backfill,
            "input_fingerprint": self.input_fingerprint,
            "ticks": self.ticks,
            "trades": [t.to_dict() for t in self.trades],
            "snapshots": [s.to_dict() for s in self.snapshots],
            "events": [_event_dict(e) for e in self.events],
            "decisions": list(self.decisions),
            "rejection_counts": dict(self.rejection_counts),
            "metrics": self.metrics.to_dict(),
            "open_at_end": [t.trade_key for t in self.open_at_end],
        }


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def decision_times(start: datetime, end: datetime, interval: timedelta) -> list[datetime]:
    """Instants in ``[start, end)`` on the epoch-aligned ``interval`` grid.

    Aligned to the epoch rather than to ``start`` so replays over different or
    adjacent windows (e.g. train and test) share one grid.
    """
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be timezone-aware")
    if interval <= timedelta(0):
        raise ValueError("decision_interval must be positive")
    n = (start - _EPOCH) // interval
    t = _EPOCH + n * interval
    if t < start:
        t += interval
    out: list[datetime] = []
    while t < end:
        out.append(t)
        t += interval
    return out


def _row_repr(row: Any) -> str:
    parts: list[str] = []
    for f in fields(row):
        v = getattr(row, f.name)
        if isinstance(v, dict):
            v = json.dumps(v, sort_keys=True, default=str)
        elif isinstance(v, datetime):
            v = v.isoformat()
        parts.append(f"{f.name}={v}")
    return "|".join(parts)


def _measured(value: Measured | None) -> Any:
    if isinstance(value, Unavailable):
        return {"unavailable": value.reason}
    if value is None:
        return None
    return str(value)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Unavailable):
        return {"unavailable": value.reason}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, dict):
        return {
            str(k): _jsonable(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _event_dict(e: MemeEvent) -> dict[str, Any]:
    return {
        "meme_id": e.meme_id,
        "event_type": e.event_type.value,
        "detected_at": e.detected_at.isoformat(),
        "mode": e.mode.value,
        "detector_version": e.detector_version,
        "mint_address": e.mint_address,
        "divergence_case": None if e.divergence_case is None else e.divergence_case.value,
        "lifecycle_state": None if e.lifecycle_state is None else e.lifecycle_state.value,
        "features": _jsonable(e.features),
        "contains_backfill": e.contains_backfill,
    }


def _event_sort_key(e: MemeEvent) -> tuple[str, str, str, str]:
    return (e.detected_at.isoformat(), e.meme_id, e.event_type.value, e.mint_address or "")


def _attention_dict(a: AttentionFeatures) -> dict[str, Any]:
    return {
        "mentions_5m": _measured(a.mentions_5m),
        "mentions_15m": _measured(a.mentions_15m),
        "mentions_1h": _measured(a.mentions_1h),
        "mentions_6h": _measured(a.mentions_6h),
        "mentions_24h": _measured(a.mentions_24h),
        "velocity": _measured(a.velocity),
        "acceleration": _measured(a.acceleration),
        "baseline_multiple": _measured(a.baseline_multiple),
        "unique_participants": _measured(a.unique_participants),
        "engagement": _measured(a.engagement),
        "platform_count": _measured(a.platform_count),
    }


def _market_dict(m: MarketFeatures) -> dict[str, Any]:
    return {
        "price_usd": _measured(m.price_usd),
        "market_cap": _measured(m.market_cap),
        "liquidity_usd": _measured(m.liquidity_usd),
        "volume_1h": _measured(m.volume_1h),
        "volume_growth": _measured(m.volume_growth),
        "price_change": _measured(m.price_change),
        "liquidity_change": _measured(m.liquidity_change),
        "token_age_seconds": (
            None if m.token_age is None else int(m.token_age.total_seconds())
        ),
        "age_bucket": m.age_bucket.value,
        "data_age_seconds": _measured(m.data_age_seconds),
    }


def _obs_visibility_floor(o: Observation, mode: ResearchMode) -> datetime:
    """A lower bound on when the PIT gate could admit ``o``. Used only to avoid
    handing the gate rows it would certainly reject; the gate decides."""
    if o.data_class is DataClass.FORWARD or mode is ResearchMode.AUTHORITATIVE:
        return o.retrieved_at
    if o.metric in ACCUMULATING_METRICS:
        return o.retrieved_at
    lag = PUBLICATION_LAG.get(o.source, timedelta(0))
    return min(o.retrieved_at, min(o.source_timestamp, o.observed_at) + lag)


class _Sliced:
    """Rows sorted by a key, sliced by bisect."""

    __slots__ = ("keys", "rows")

    def __init__(self, keyed: Iterable[tuple[datetime, str, Any]]) -> None:
        ordered = sorted(keyed, key=lambda r: (r[0], r[1]))
        self.keys: list[datetime] = [r[0] for r in ordered]
        self.rows: list[Any] = [r[2] for r in ordered]

    def window(self, lo: datetime, hi: datetime) -> tuple[Any, ...]:
        return tuple(self.rows[bisect_left(self.keys, lo) : bisect_right(self.keys, hi)])


class _MintIndex:
    """One mint's market readings, sorted by (available_at, observed_at, row)."""

    __slots__ = ("keys", "points", "prefix_latest")

    def __init__(self, points: Iterable[tuple[str, MarketPoint]]) -> None:
        ordered = sorted(points, key=lambda r: (r[1].available_at, r[1].observed_at, r[0]))
        self.points: list[MarketPoint] = [p for _, p in ordered]
        self.keys: list[datetime] = [p.available_at for p in self.points]
        # prefix_latest[i]: index of the newest reading among points[0..i], by
        # the same key ``market.market_features`` uses for "latest", so the
        # entry price is exactly the price the strategy's features saw.
        self.prefix_latest: list[int] = []
        best = -1
        for i, p in enumerate(self.points):
            if best < 0 or _latest_key(p) >= _latest_key(self.points[best]):
                best = i
            self.prefix_latest.append(best)

    def visible_end(self, t: datetime) -> int:
        return bisect_right(self.keys, t)

    def latest(self, t: datetime) -> MarketPoint | None:
        """The newest reading available at ``t``. Its price may be None —
        that is "no current price", and nothing older is substituted."""
        end = self.visible_end(t)
        return None if end == 0 else self.points[self.prefix_latest[end - 1]]

    def first_visible(self, t: datetime) -> MarketPoint | None:
        end = self.visible_end(t)
        return None if end == 0 else min(self.points[:end], key=_latest_key)


def _latest_key(p: MarketPoint) -> tuple[datetime, datetime, str, str]:
    # Mirrors app.lifecycle_lab.market._key (private there).
    return (p.observed_at, p.available_at, p.source, p.data_class.value)


@dataclass(slots=True)
class _MemeIndex:
    meme: Meme
    aliases: tuple[MemeAlias, ...]
    links: tuple[MemeTokenLink, ...]
    tokens: tuple[TokenInfo, ...]
    observations: _Sliced
    market: _Sliced
    runs: _Sliced
    events: list[MemeEvent] = field(default_factory=list)


@dataclass(slots=True)
class _MemeTick:
    state: InformationState
    attention: AttentionFeatures
    market: dict[str, MarketFeatures]
    #: Per visible mint: the PUMPING rule reads that mint's price.
    lifecycle_state: dict[str, LifecycleState]


@dataclass(slots=True)
class _OpenRuntime:
    meme_id: str
    exit_state: PositionExitState
    cursor: int
    notes_seen: set[str]


# --------------------------------------------------------------------------
# Fingerprint
# --------------------------------------------------------------------------


def input_fingerprint(
    *,
    reprs: dict[str, list[str]],
    cfg: LabConfig,
    mode: ResearchMode,
    arm: Arm,
    start: datetime,
    end: datetime,
    hindsight_links: bool,
    history_lookback: timedelta | None,
) -> str:
    h = hashlib.sha256()
    header = spec_hash(
        {
            "config": cfg.as_spec(),
            "strategy": strategy.strategy_spec(arm, cfg.baseline),
            "mode": mode,
            "arm": arm,
            "start": start,
            "end": end,
            "hindsight_links": hindsight_links,
            "history_lookback": history_lookback,
        }
    )
    h.update(header.encode())
    for name in sorted(reprs):
        h.update(f"\n#{name}\n".encode())
        for line in sorted(reprs[name]):
            h.update(line.encode())
            h.update(b"\n")
    return h.hexdigest()


# --------------------------------------------------------------------------
# The replay
# --------------------------------------------------------------------------


def run_replay(
    *,
    inputs: ReplayInputs,
    cfg: LabConfig,
    mode: ResearchMode,
    arm: Arm,
    start: datetime,
    end: datetime,
    hindsight_links: bool = False,
    history_lookback: timedelta | None = None,
) -> ReplayResult:
    """Replay ``[start, end)`` at ``cfg.decision_interval``.

    ``history_lookback`` optionally bounds how far back each instant's rows
    reach. The default (``None``) hands the engines every row known at ``T``,
    which they need: revival and DEAD compare against *all* prior history, so
    a bound can change what they detect. It is an opt-in for long replays
    where that trade is acceptable, and it is part of the fingerprint because
    it is part of what the engines saw.
    """
    if mode is ResearchMode.AUTHORITATIVE and hindsight_links:
        raise ValueError("AUTHORITATIVE mode refuses hindsight_links")
    if end <= start:
        raise ValueError("end must be after start")
    lookback = history_lookback
    authoritative = mode is ResearchMode.AUTHORITATIVE

    # ---- canonicalise inputs ------------------------------------------------
    reprs: dict[str, list[str]] = {}

    def keyed(name: str, rows: Sequence[Any]) -> list[tuple[str, Any]]:
        out = [(_row_repr(r), r) for r in rows]
        reprs[name] = [k for k, _ in out]
        return out

    memes = sorted(keyed("memes", inputs.memes), key=lambda r: (r[1].id, r[0]))
    aliases = sorted(keyed("aliases", inputs.aliases))
    links = sorted(keyed("links", inputs.links))
    tokens = sorted(keyed("tokens", inputs.tokens))
    observations = keyed("observations", inputs.observations)
    market_rows = keyed("market", inputs.market)
    runs = keyed("runs", inputs.runs)

    fingerprint = input_fingerprint(
        reprs=reprs,
        cfg=cfg,
        mode=mode,
        arm=arm,
        start=start,
        end=end,
        hindsight_links=hindsight_links,
        history_lookback=lookback,
    )

    if authoritative:
        observations = [r for r in observations if r[1].data_class is DataClass.FORWARD]
        market_rows = [r for r in market_rows if r[1].data_class is DataClass.FORWARD]
        runs = [r for r in runs if r[1].data_class is DataClass.FORWARD]

    mint_points: dict[str, list[tuple[str, MarketPoint]]] = {}
    for k, p in market_rows:
        mint_points.setdefault(p.mint_address, []).append((k, p))
    mint_index = {m: _MintIndex(pts) for m, pts in mint_points.items()}

    indexes: list[_MemeIndex] = []
    for _, meme in memes:
        meme_links = tuple(link for _, link in links if link.meme_id == meme.id)
        mints = {link.mint_address for link in meme_links}
        indexes.append(
            _MemeIndex(
                meme=meme,
                aliases=tuple(a for _, a in aliases if a.meme_id == meme.id),
                links=meme_links,
                tokens=tuple(t for _, t in tokens if t.mint_address in mints),
                observations=_Sliced(
                    (_obs_visibility_floor(o, mode), k, o)
                    for k, o in observations
                    if o.meme_id == meme.id
                    or (o.mint_address is not None and o.mint_address in mints)
                ),
                market=_Sliced(
                    (p.available_at, k, p) for k, p in market_rows if p.mint_address in mints
                ),
                runs=_Sliced(
                    (r.finished_at, k, r)
                    for k, r in runs
                    if r.meme_id == meme.id
                    or (r.mint_address is not None and r.mint_address in mints)
                    or (r.meme_id is None and r.mint_address is None)
                ),
            )
        )

    # ---- state ---------------------------------------------------------------
    portfolio = Portfolio(cfg.portfolio)
    runtime: dict[str, _OpenRuntime] = {}
    decision_log: list[dict[str, Any]] = []
    last_outcome: dict[tuple[str, str], tuple[Any, ...]] = {}
    open_runs: dict[tuple[str, str], dict[str, Any]] = {}
    rejection_counts: dict[str, int] = {}
    snapshots: list[PortfolioSnapshot] = []
    any_backfill = False
    wired = strategy.is_wired(arm)

    def log(
        t: datetime, meme_id: str, mint: str, outcome: tuple[Any, ...], row: dict[str, Any]
    ) -> None:
        key = (meme_id, mint)
        if last_outcome.get(key) == outcome and key in open_runs:
            run = open_runs[key]
            run["until"] = t.isoformat()
            run["ticks"] += 1
            return
        last_outcome[key] = outcome
        entry = {"at": t.isoformat(), "until": t.isoformat(), "ticks": 1, **row}
        open_runs[key] = entry
        decision_log.append(entry)

    ticks = decision_times(start, end, cfg.decision_interval)

    for t in ticks:
        lo = _MIN_TIME if lookback is None else t - lookback
        # ---- phase 1: what was known about each meme ---------------------
        known: dict[str, _MemeTick] = {}
        for idx in indexes:
            state = pit.information_available_at(
                as_of=t,
                mode=mode,
                meme=idx.meme,
                aliases=idx.aliases,
                links=idx.links,
                tokens=idx.tokens,
                observations=idx.observations.window(lo, t),
                market=idx.market.window(lo, t),
                runs=idx.runs.window(lo, t),
                hindsight_links=hindsight_links,
                max_observation_age=cfg.attention.max_observation_age,
            )
            any_backfill = any_backfill or state.contains_backfill
            attn = attention_engine.attention_features(state, cfg.attention)
            visible_mints = sorted({link.mint_address for link in state.links})
            mkt = {m: market_engine.market_features(state, m) for m in visible_mints}
            # The event and state engines take one market at a time. Meme-level
            # events are deduplicated by the engine against prior_events, so
            # calling once per mint (accumulating) fires each of them once.
            for mf in mkt.values() if mkt else (None,):
                idx.events.extend(
                    sorted(
                        events_engine.detect_events(
                            state=state,
                            attention=attn,
                            market=mf,
                            prior_events=tuple(idx.events),
                            cfg=cfg.events,
                        ),
                        key=_event_sort_key,
                    )
                )
            prior = tuple(idx.events)
            lstates = {
                m: states_engine.classify_state(
                    state=state, attention=attn, market=mf, prior_events=prior, cfg=cfg.events
                )
                for m, mf in mkt.items()
            }
            known[idx.meme.id] = _MemeTick(state, attn, mkt, lstates)

        # ---- phase 2: exits ----------------------------------------------
        for trade in portfolio.open_trades:
            rt = runtime[trade.trade_key]
            mi = mint_index.get(trade.mint_address)
            if mi is None:
                continue
            end_i = mi.visible_end(t)
            batch = mi.points[rt.cursor : end_i]
            meme_tick = known.get(rt.meme_id)
            attn_now: Measured | None = (
                None if meme_tick is None else meme_tick.attention.mentions_1h
            )
            last_priced = max(
                (
                    i
                    for i, p in enumerate(batch)
                    if p.price_usd is not None and p.price_usd > 0
                ),
                default=-1,
            )
            closed = False
            notes: list[str] = []
            for i, point in enumerate(batch):
                ev = evaluate_exit(
                    position=rt.exit_state,
                    point=point,
                    cfg=cfg.exits,
                    attention_1h=attn_now if i == last_priced else None,
                    attention_as_of=t if i == last_priced else None,
                )
                rt.exit_state = PositionExitState(
                    entry_at=rt.exit_state.entry_at,
                    entry_price=rt.exit_state.entry_price,
                    peak_price=ev.peak_price,
                    entry_volume_1h=rt.exit_state.entry_volume_1h,
                    entry_attention_1h=rt.exit_state.entry_attention_1h,
                )
                notes.extend(ev.notes)
                if ev.signal is not None:
                    _annotate(portfolio, rt, trade.trade_key, notes, t)
                    portfolio.close(
                        trade.trade_key,
                        ev.signal,
                        contains_backfill=point.data_class is DataClass.BACKFILL,
                    )
                    any_backfill = any_backfill or point.data_class is DataClass.BACKFILL
                    del runtime[trade.trade_key]
                    closed = True
                    break
            if closed:
                continue
            rt.cursor = end_i
            if last_priced < 0 and attn_now is not None:
                latest = mi.latest(t)
                if latest is not None:
                    ev = evaluate_attention_collapse(
                        position=rt.exit_state,
                        point=latest,
                        attention_1h=attn_now,
                        attention_as_of=t,
                        cfg=cfg.exits,
                    )
                    notes.extend(ev.notes)
                    if ev.signal is not None:
                        _annotate(portfolio, rt, trade.trade_key, notes, t)
                        portfolio.close(
                            trade.trade_key,
                            ev.signal,
                            contains_backfill=latest.data_class is DataClass.BACKFILL,
                        )
                        any_backfill = any_backfill or latest.data_class is DataClass.BACKFILL
                        del runtime[trade.trade_key]
                        continue
            _annotate(portfolio, rt, trade.trade_key, notes, t)

        # ---- phase 3: entries --------------------------------------------
        for idx in indexes:
            mt = known[idx.meme.id]
            if not mt.market:
                log(
                    t,
                    idx.meme.id,
                    "",
                    ("no_visible_link",),
                    {
                        "meme_id": idx.meme.id,
                        "mint_address": None,
                        "status": "no_entry",
                        "reason_code": "no_visible_link",
                        "failed_conditions": [],
                        "unavailable": {},
                        "rejection": None,
                        "trade_key": None,
                    },
                )
                continue
            for mint, mf in mt.market.items():
                row = _decide_and_enter(
                    t=t,
                    arm=arm,
                    wired=wired,
                    cfg=cfg,
                    meme_index=idx,
                    meme_tick=mt,
                    mint=mint,
                    mf=mf,
                    mint_index=mint_index.get(mint),
                    portfolio=portfolio,
                    runtime=runtime,
                    hindsight_links=hindsight_links,
                )
                if row.get("rejection"):
                    rejection_counts[row["rejection"]] = (
                        rejection_counts.get(row["rejection"], 0) + 1
                    )
                if row.get("entry_backfill"):
                    any_backfill = True
                row.pop("entry_backfill", None)
                outcome = (
                    row["status"],
                    row["reason_code"],
                    tuple(row["failed_conditions"]),
                    row["rejection"],
                    row["trade_key"],
                )
                log(t, idx.meme.id, mint, outcome, row)

        # ---- snapshot ----------------------------------------------------
        snap = portfolio.snapshot(t, _marks(portfolio, mint_index, t))
        if not snapshots or _snap_changed(snapshots[-1], snap):
            snapshots.append(snap)

    final_at = ticks[-1] if ticks else start
    if ticks and snapshots[-1].at != final_at:
        snapshots.append(portfolio.snapshot(final_at, _marks(portfolio, mint_index, final_at)))
    if not ticks:
        snapshots.append(portfolio.snapshot(start, {}))

    open_at_end = portfolio.mark_end_of_data()
    trades = tuple(
        sorted((*portfolio.closed, *open_at_end), key=lambda tr: (tr.entry_at, tr.trade_key))
    )
    all_events = tuple(sorted((e for idx in indexes for e in idx.events), key=_event_sort_key))
    metrics = compute_metrics(
        trades, snapshots, starting_capital=cfg.portfolio.starting_capital
    )
    return ReplayResult(
        mode=mode,
        arm=arm,
        start=start,
        end=end,
        hindsight_links=hindsight_links,
        contains_backfill=any_backfill,
        input_fingerprint=fingerprint,
        ticks=len(ticks),
        trades=trades,
        snapshots=tuple(snapshots),
        events=all_events,
        decisions=tuple(decision_log),
        rejection_counts=dict(sorted(rejection_counts.items())),
        metrics=metrics,
        open_at_end=open_at_end,
    )


def _annotate(
    portfolio: Portfolio, rt: _OpenRuntime, key: str, notes: list[str], t: datetime
) -> None:
    """Put each exit rule that could not be checked on the trade's timeline,
    once per distinct note — the first time it happened is the fact."""
    fresh = []
    for note in notes:
        if note not in rt.notes_seen:
            rt.notes_seen.add(note)
            fresh.append(
                {"at": t.isoformat(), "kind": "exit_check_unavailable", "detail": note}
            )
    portfolio.annotate(key, tuple(fresh))


def _marks(
    portfolio: Portfolio, mint_index: dict[str, _MintIndex], t: datetime
) -> dict[str, Decimal | None]:
    marks: dict[str, Decimal | None] = {}
    for trade in portfolio.open_trades:
        mi = mint_index.get(trade.mint_address)
        point = None if mi is None else mi.latest(t)
        marks[trade.mint_address] = None if point is None else point.price_usd
    return marks


def _snap_changed(a: PortfolioSnapshot, b: PortfolioSnapshot) -> bool:
    return (a.equity, a.cash, a.open_positions, a.unrealized_pnl, a.realized_pnl) != (
        b.equity,
        b.cash,
        b.open_positions,
        b.unrealized_pnl,
        b.realized_pnl,
    )


def _count_points(state: InformationState, mint: str, since: datetime) -> int:
    return sum(
        1
        for p in state.market
        if p.mint_address == mint
        and p.observed_at >= since
        and p.price_usd is not None
        and p.price_usd > 0
    )


def _decide_and_enter(
    *,
    t: datetime,
    arm: Arm,
    wired: bool,
    cfg: LabConfig,
    meme_index: _MemeIndex,
    meme_tick: _MemeTick,
    mint: str,
    mf: MarketFeatures,
    mint_index: _MintIndex | None,
    portfolio: Portfolio,
    runtime: dict[str, _OpenRuntime],
    hindsight_links: bool,
) -> dict[str, Any]:
    meme_id = meme_index.meme.id
    row: dict[str, Any] = {
        "meme_id": meme_id,
        "mint_address": mint,
        "rejection": None,
        "trade_key": None,
    }
    state = meme_tick.state
    window = cfg.baseline.run_up_window
    run_up: Measured = (
        mf.price_change
        if window == timedelta(hours=1)
        else market_engine.market_features(state, mint, window=window).price_change
    )
    inp = strategy.StrategyInputs(
        attention=meme_tick.attention,
        market=mf,
        run_up=run_up,
        market_points=_count_points(state, mint, t - window),
    )
    decision = strategy.decide(arm, inp, cfg.baseline)
    row.update(
        status=decision.status,
        reason_code=decision.reason_code,
        failed_conditions=list(decision.failed_conditions),
        unavailable={
            k: v["unavailable"]
            for k, v in sorted(decision.evidence.items())
            if isinstance(v, dict) and "unavailable" in v
        },
    )
    if not wired or not decision.enter:
        return row

    point = None if mint_index is None else mint_index.latest(t)
    divergence = divergence_engine.classify_divergence(meme_tick.attention, mf, cfg.events)
    token_age = mf.token_age
    req = EntryRequest(
        at=t,
        arm=arm,
        meme_id=meme_id,
        mint_address=mint,
        price=None if point is None else point.price_usd,
        liquidity_usd=None if point is None else point.liquidity_usd,
        market_cap=None if point is None else point.market_cap,
        token_age_seconds=None if token_age is None else int(token_age.total_seconds()),
        age_bucket=mf.age_bucket
        if isinstance(mf.age_bucket, AgeBucket)
        else AgeBucket.UNKNOWN,
        lifecycle_state=meme_tick.lifecycle_state.get(mint, LifecycleState.UNKNOWN),
        divergence_case=(
            divergence if isinstance(divergence, DivergenceCase) else DivergenceCase.NONE
        ),
        entry_reason=decision.reason_code,
        entry_features={
            "attention": _attention_dict(meme_tick.attention),
            "market": _market_dict(mf),
            "run_up": _measured(run_up),
            "market_points": inp.market_points,
            "decision": _jsonable(decision.evidence),
        },
        evidence_timeline=_timeline(
            t=t,
            meme_index=meme_index,
            state=state,
            mint=mint,
            point=point,
            mint_index=mint_index,
            reason=decision.reason_code,
            arm=arm,
            hindsight_links=hindsight_links,
        ),
        contains_backfill=state.contains_backfill
        or (point is not None and point.data_class is DataClass.BACKFILL),
        hindsight=hindsight_links,
    )
    result = portfolio.try_open(req)
    if isinstance(result, Rejection):
        row["rejection"] = result.reason
        return row
    row["trade_key"] = result.trade_key
    row["entry_backfill"] = result.contains_backfill
    entry_volume: Measured = mf.volume_1h
    if point is not None and point.volume_1h is not None:
        # The collapse rule compares a reading's volume_1h with the entry's,
        # so both come from the same field of the same kind of row.
        entry_volume = point.volume_1h
    assert point is not None and point.price_usd is not None
    runtime[result.trade_key] = _OpenRuntime(
        meme_id=meme_id,
        exit_state=PositionExitState(
            entry_at=t,
            entry_price=point.price_usd,
            peak_price=point.price_usd,
            entry_volume_1h=entry_volume,
            entry_attention_1h=meme_tick.attention.mentions_1h,
        ),
        cursor=mint_index.visible_end(t) if mint_index is not None else 0,
        notes_seen=set(),
    )
    return row


def _timeline(
    *,
    t: datetime,
    meme_index: _MemeIndex,
    state: InformationState,
    mint: str,
    point: MarketPoint | None,
    mint_index: _MintIndex | None,
    reason: str,
    arm: Arm,
    hindsight_links: bool,
) -> tuple[dict[str, Any], ...]:
    """What preceded the entry and was visible at ``t`` — and the entry."""
    items: list[dict[str, Any]] = []
    meme = meme_index.meme
    if meme.tracking_started_at <= t:
        items.append(
            {
                "at": meme.tracking_started_at.isoformat(),
                "kind": "meme_tracking_started",
                "detail": {"meme_id": meme.id},
            }
        )
    for link in state.links:
        if link.mint_address != mint:
            continue
        items.append(
            {
                "at": link.linked_at.isoformat(),
                "kind": "link_created",
                "detail": {
                    "method": link.method.value,
                    "confidence": str(link.confidence),
                    "hindsight": hindsight_links and link.linked_at > t,
                },
            }
        )
    for token in state.tokens:
        if (
            token.mint_address == mint
            and token.created_at is not None
            and token.created_at <= t
        ):
            items.append(
                {
                    "at": token.created_at.isoformat(),
                    "kind": "token_created",
                    "detail": {"mint_address": mint},
                }
            )
    if mint_index is not None:
        first = mint_index.first_visible(t)
        if first is not None:
            items.append(
                {
                    "at": first.observed_at.isoformat(),
                    "kind": "first_market_reading",
                    "detail": {"price_usd": _measured(first.price_usd)},
                }
            )
    visible_events = [
        e
        for e in meme_index.events
        if e.detected_at <= t and (e.mint_address is None or e.mint_address == mint)
    ]
    for e in visible_events[-MAX_TIMELINE_EVENTS:]:
        items.append(
            {
                "at": e.detected_at.isoformat(),
                "kind": f"event:{e.event_type.value}",
                "detail": {
                    "mint_address": e.mint_address,
                    "divergence_case": (
                        None if e.divergence_case is None else e.divergence_case.value
                    ),
                    "lifecycle_state": (
                        None if e.lifecycle_state is None else e.lifecycle_state.value
                    ),
                },
            }
        )
    if point is not None:
        items.append(
            {
                "at": point.observed_at.isoformat(),
                "kind": "entry_price_reading",
                "detail": {
                    "available_at": point.available_at.isoformat(),
                    "price_usd": _measured(point.price_usd),
                    "source": point.source,
                    "data_class": point.data_class.value,
                },
            }
        )
    items.sort(key=lambda d: (d["at"], d["kind"]))
    items.append(
        {
            "at": t.isoformat(),
            "kind": "entry",
            "detail": {"reason_code": reason, "arm": arm.value},
        }
    )
    return tuple(items)
