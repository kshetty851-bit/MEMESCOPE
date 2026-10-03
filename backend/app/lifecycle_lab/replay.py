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

**Resumable.** The replay is a fold over decision ticks with an explicit
``ReplayState`` (portfolio ledger, open positions and their exit memory,
per-meme prior events, decision-log compaction, counters). ``run_replay`` folds
from ``ReplayState.initial``; ``resume_replay`` continues from any state it, or
an earlier ``resume_replay``, returned — and the result is identical to the
uninterrupted replay (``tests/unit/test_mll_incremental.py``). The state at
tick ``T`` depends only on what was visible at or before ``T``; whether the
inputs still say the same about ``<= T`` is ``checkpoint.py``'s question.

Pure: no I/O, no clock, no randomness. Inputs are canonically sorted, so the
input order does not matter, and ``input_fingerprint`` identifies them.
"""

from __future__ import annotations

import hashlib
import json
from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Mapping, Sequence
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
    EventType,
    ExitReason,
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
_ZERO = Decimal(0)
#: Bump on ANY change to what the fold computes or carries — engines, state
#: layout, tick order. A checkpoint from another version is never resumed
#: (``checkpoint.is_valid``); the engine-source hash backs this up for edits
#: that forget to bump it.
REPLAY_VERSION = "mll-replay-v2"
#: Layout of ``ReplayState.to_json``.
STATE_FORMAT = 1
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


def obs_visibility_floor(o: Observation, mode: ResearchMode) -> datetime:
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
    #: The tick at which ``cursor`` was last set (see ``OpenPosition``).
    cursor_at: datetime
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
# Resumable state
# --------------------------------------------------------------------------


def config_hash(cfg: LabConfig, arm: Arm) -> str:
    """Everything in the configuration a replay's state depends on: the lab
    config and the arm's strategy spec. A state built under one hash cannot
    be continued under another."""
    return spec_hash(
        {"config": cfg.as_spec(), "strategy": strategy.strategy_spec(arm, cfg.baseline)}
    )


@dataclass(frozen=True, slots=True)
class OpenPosition:
    """An open paper position and everything its exit rules carry between
    ticks."""

    #: The ledger's copy, evidence timeline so far included.
    trade: PaperTrade
    meme_id: str
    exit_state: PositionExitState
    #: Market readings available at or before this tick have been evaluated.
    #: A time, not a list index: the index of "the first unevaluated reading"
    #: is recomputed from the inputs on resume (``_MintIndex.visible_end``),
    #: so it cannot go stale if rows *after* this instant arrive.
    cursor_at: datetime
    #: Exit rules already reported as uncheckable (once per distinct note).
    notes_seen: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReplayState:
    """Everything the fold carries from one decision tick to the next — and
    everything a result is assembled from.

    ``run_replay`` is ``resume_replay`` from ``ReplayState.initial``. The state
    after tick ``T`` is a function of the inputs visible at or before ``T``
    only (the PIT gate sees nothing later, and nothing here is computed from a
    later row), which is what makes continuing from it equivalent to never
    having stopped. ``to_json``/``from_json`` round-trip it exactly, Decimals
    as strings, so it can be stored as a checkpoint.

    Immutable by convention as well as by type: the fold copies whatever it
    will mutate (the open decision runs) when it restores and when it exports.
    """

    # -- identity: a state only continues the replay it came from ----------
    mode: ResearchMode
    arm: Arm
    start: datetime
    hindsight_links: bool
    history_lookback: timedelta | None
    config_hash: str
    #: Meme ids in the replay's canonical order.
    meme_ids: tuple[str, ...]
    # -- progress -------------------------------------------------------------
    ticks: int
    #: The last decision tick folded in; ``None`` before the first.
    processed_until: datetime | None
    # -- portfolio ledger -----------------------------------------------------
    cash: Decimal
    realized_pnl: Decimal
    peak_equity: Decimal
    #: In ledger insertion order: valuation sums over it, and Decimal sums are
    #: only reproducible in the same order.
    open_positions: tuple[OpenPosition, ...]
    #: Closed trades in the order they closed.
    closed: tuple[PaperTrade, ...]
    #: The equity curve as appended (a point only when something changed).
    snapshots: tuple[PortfolioSnapshot, ...]
    #: The most recent valuation, appended or not — the curve's closing point.
    last_snapshot: PortfolioSnapshot | None
    # -- per meme: prior events (the event engine's episode / re-arm memory) -
    #: Per meme index, in canonical meme order, events in accumulation order.
    events: tuple[tuple[str, tuple[MemeEvent, ...]], ...]
    # -- decision log ---------------------------------------------------------
    #: The run-length decision log so far.
    decisions: tuple[dict[str, Any], ...]
    #: Compaction state: per (meme, mint), the index of its open run in
    #: ``decisions`` and that run's outcome (canonical JSON).
    open_runs: tuple[tuple[str, str, int, str], ...]
    rejection_counts: tuple[tuple[str, int], ...]
    any_backfill: bool

    @classmethod
    def initial(
        cls,
        *,
        inputs: ReplayInputs,
        cfg: LabConfig,
        mode: ResearchMode,
        arm: Arm,
        start: datetime,
        hindsight_links: bool = False,
        history_lookback: timedelta | None = None,
    ) -> ReplayState:
        """The state before the first tick of a replay starting at ``start``."""
        if start.tzinfo is None:
            raise ValueError("start must be timezone-aware")
        ids = _canonical_meme_ids(inputs)
        cap = cfg.portfolio.starting_capital
        return cls(
            mode=mode,
            arm=arm,
            start=start,
            hindsight_links=hindsight_links,
            history_lookback=history_lookback,
            config_hash=config_hash(cfg, arm),
            meme_ids=ids,
            ticks=0,
            processed_until=None,
            cash=cap,
            realized_pnl=_ZERO,
            peak_equity=cap,
            open_positions=(),
            closed=(),
            snapshots=(),
            last_snapshot=None,
            events=tuple((m, ()) for m in ids),
            decisions=(),
            open_runs=(),
            rejection_counts=(),
            any_backfill=False,
        )

    # -- JSON ------------------------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        """A JSON-safe document (``json.dumps`` accepts it as-is)."""
        return {
            "format": STATE_FORMAT,
            "replay_version": REPLAY_VERSION,
            "mode": self.mode.value,
            "arm": self.arm.value,
            "start": self.start.isoformat(),
            "hindsight_links": self.hindsight_links,
            "history_lookback_us": (
                None if self.history_lookback is None else _td_to_us(self.history_lookback)
            ),
            "config_hash": self.config_hash,
            "meme_ids": list(self.meme_ids),
            "ticks": self.ticks,
            "processed_until": _iso(self.processed_until),
            "cash": str(self.cash),
            "realized_pnl": str(self.realized_pnl),
            "peak_equity": str(self.peak_equity),
            "open_positions": [_position_to_json(p) for p in self.open_positions],
            "closed": [t.to_dict() for t in self.closed],
            "snapshots": [_snapshot_to_json(s) for s in self.snapshots],
            "last_snapshot": (
                None if self.last_snapshot is None else _snapshot_to_json(self.last_snapshot)
            ),
            "events": [[m, [_event_to_json(e) for e in evs]] for m, evs in self.events],
            "decisions": [dict(d) for d in self.decisions],
            "open_runs": [list(r) for r in self.open_runs],
            "rejection_counts": [[k, v] for k, v in self.rejection_counts],
            "any_backfill": self.any_backfill,
        }

    @classmethod
    def from_json(cls, doc: Mapping[str, Any] | str) -> ReplayState:
        """Inverse of ``to_json``. Refuses a document written by another state
        format or replay version — such a state describes a different engine."""
        d: Mapping[str, Any] = json.loads(doc) if isinstance(doc, str) else doc
        if d.get("format") != STATE_FORMAT:
            raise ValueError(f"unsupported replay state format: {d.get('format')!r}")
        if d.get("replay_version") != REPLAY_VERSION:
            raise ValueError(f"replay state from another engine: {d.get('replay_version')!r}")
        lookback = d["history_lookback_us"]
        last = d["last_snapshot"]
        return cls(
            mode=ResearchMode(d["mode"]),
            arm=Arm(d["arm"]),
            start=datetime.fromisoformat(d["start"]),
            hindsight_links=bool(d["hindsight_links"]),
            history_lookback=None if lookback is None else timedelta(microseconds=lookback),
            config_hash=str(d["config_hash"]),
            meme_ids=tuple(str(m) for m in d["meme_ids"]),
            ticks=int(d["ticks"]),
            processed_until=_from_iso(d["processed_until"]),
            cash=Decimal(d["cash"]),
            realized_pnl=Decimal(d["realized_pnl"]),
            peak_equity=Decimal(d["peak_equity"]),
            open_positions=tuple(_position_from_json(p) for p in d["open_positions"]),
            closed=tuple(_trade_from_json(t) for t in d["closed"]),
            snapshots=tuple(_snapshot_from_json(s) for s in d["snapshots"]),
            last_snapshot=None if last is None else _snapshot_from_json(last),
            events=tuple(
                (str(m), tuple(_event_from_json(e) for e in evs)) for m, evs in d["events"]
            ),
            decisions=tuple(dict(x) for x in d["decisions"]),
            open_runs=tuple(
                (str(m), str(mint), int(i), str(o)) for m, mint, i, o in d["open_runs"]
            ),
            rejection_counts=tuple((str(k), int(v)) for k, v in d["rejection_counts"]),
            any_backfill=bool(d["any_backfill"]),
        )


def _td_to_us(value: timedelta) -> int:
    return value // timedelta(microseconds=1)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _from_iso(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def _dec(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _measured_to_json(value: Measured) -> dict[str, str]:
    if isinstance(value, Unavailable):
        return {"u": value.reason}
    return {"d": str(value)}


def _measured_from_json(doc: Mapping[str, str]) -> Measured:
    if "u" in doc:
        return Unavailable(doc["u"])
    return Decimal(doc["d"])


def _snapshot_to_json(s: PortfolioSnapshot) -> list[Any]:
    # Positional, not keyed: the equity curve is the bulk of a long state.
    return [
        s.at.isoformat(),
        _s(s.equity),
        str(s.cash),
        str(s.deployed),
        str(s.realized_pnl),
        _s(s.unrealized_pnl),
        s.open_positions,
        str(s.peak_equity),
        _s(s.drawdown),
    ]


def _snapshot_from_json(row: Sequence[Any]) -> PortfolioSnapshot:
    at, equity, cash, deployed, realized, unrealized, n_open, peak, drawdown = row
    return PortfolioSnapshot(
        at=datetime.fromisoformat(at),
        equity=_dec(equity),
        cash=Decimal(cash),
        deployed=Decimal(deployed),
        realized_pnl=Decimal(realized),
        unrealized_pnl=_dec(unrealized),
        open_positions=int(n_open),
        peak_equity=Decimal(peak),
        drawdown=_dec(drawdown),
    )


def _s(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _trade_from_json(d: Mapping[str, Any]) -> PaperTrade:
    exit_reason = d["exit_reason"]
    return PaperTrade(
        trade_key=d["trade_key"],
        arm=Arm(d["arm"]),
        meme_id=d["meme_id"],
        mint_address=d["mint_address"],
        entry_at=datetime.fromisoformat(d["entry_at"]),
        entry_price=Decimal(d["entry_price"]),
        size_usd=Decimal(d["size_usd"]),
        quantity=Decimal(d["quantity"]),
        entry_fees_usd=Decimal(d["entry_fees_usd"]),
        entry_market_cap=_dec(d["entry_market_cap"]),
        entry_liquidity_usd=_dec(d["entry_liquidity_usd"]),
        token_age_seconds=d["token_age_seconds"],
        age_bucket=AgeBucket(d["age_bucket"]),
        lifecycle_state=LifecycleState(d["lifecycle_state"]),
        divergence_case=DivergenceCase(d["divergence_case"]),
        entry_reason=d["entry_reason"],
        entry_features=dict(d["entry_features"]),
        evidence_timeline=tuple(dict(e) for e in d["evidence_timeline"]),
        cost_model=d["cost_model"],
        exit_at=_from_iso(d["exit_at"]),
        exit_price=_dec(d["exit_price"]),
        exit_reason=None if exit_reason is None else ExitReason(exit_reason),
        exit_fees_usd=_dec(d["exit_fees_usd"]),
        pnl_usd=_dec(d["pnl_usd"]),
        return_pct=_dec(d["return_pct"]),
        status=d["status"],
        contains_backfill=bool(d["contains_backfill"]),
        hindsight=bool(d["hindsight"]),
    )


def _event_to_json(e: MemeEvent) -> dict[str, Any]:
    # ``features`` is built JSON-safe by the event engine (``events.json_safe``)
    # and is stored as-is: re-normalising it here could change what a resumed
    # detector reads back as its prior.
    return {**_event_dict(e), "features": e.features}


def _event_from_json(d: Mapping[str, Any]) -> MemeEvent:
    case = d["divergence_case"]
    lstate = d["lifecycle_state"]
    return MemeEvent(
        meme_id=d["meme_id"],
        event_type=EventType(d["event_type"]),
        detected_at=datetime.fromisoformat(d["detected_at"]),
        mode=ResearchMode(d["mode"]),
        detector_version=d["detector_version"],
        mint_address=d["mint_address"],
        divergence_case=None if case is None else DivergenceCase(case),
        lifecycle_state=None if lstate is None else LifecycleState(lstate),
        features=dict(d["features"]),
        contains_backfill=bool(d["contains_backfill"]),
    )


def _position_to_json(p: OpenPosition) -> dict[str, Any]:
    x = p.exit_state
    return {
        "trade": p.trade.to_dict(),
        "meme_id": p.meme_id,
        "exit_state": {
            "entry_at": x.entry_at.isoformat(),
            "entry_price": str(x.entry_price),
            "peak_price": str(x.peak_price),
            "entry_volume_1h": _measured_to_json(x.entry_volume_1h),
            "entry_attention_1h": _measured_to_json(x.entry_attention_1h),
        },
        "cursor_at": p.cursor_at.isoformat(),
        "notes_seen": list(p.notes_seen),
    }


def _position_from_json(d: Mapping[str, Any]) -> OpenPosition:
    x = d["exit_state"]
    return OpenPosition(
        trade=_trade_from_json(d["trade"]),
        meme_id=d["meme_id"],
        exit_state=PositionExitState(
            entry_at=datetime.fromisoformat(x["entry_at"]),
            entry_price=Decimal(x["entry_price"]),
            peak_price=Decimal(x["peak_price"]),
            entry_volume_1h=_measured_from_json(x["entry_volume_1h"]),
            entry_attention_1h=_measured_from_json(x["entry_attention_1h"]),
        ),
        cursor_at=datetime.fromisoformat(d["cursor_at"]),
        notes_seen=tuple(str(n) for n in d["notes_seen"]),
    )


class _Ledger(Portfolio):
    """The portfolio ledger, restorable from and exportable to a state."""

    def load(self, state: ReplayState) -> None:
        self.cash = state.cash
        self.realized_pnl = state.realized_pnl
        self.peak_equity = state.peak_equity
        for pos in state.open_positions:
            self._open[pos.trade.trade_key] = pos.trade
            self._open_by_mint[pos.trade.mint_address] = pos.trade.trade_key
        self.closed = list(state.closed)

    def in_ledger_order(self) -> tuple[PaperTrade, ...]:
        return tuple(self._open.values())


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

    Exactly ``resume_replay`` from ``ReplayState.initial``.
    """
    if mode is ResearchMode.AUTHORITATIVE and hindsight_links:
        raise ValueError("AUTHORITATIVE mode refuses hindsight_links")
    if end <= start:
        raise ValueError("end must be after start")
    state = ReplayState.initial(
        inputs=inputs,
        cfg=cfg,
        mode=mode,
        arm=arm,
        start=start,
        hindsight_links=hindsight_links,
        history_lookback=history_lookback,
    )
    result, _ = resume_replay(
        state=state,
        inputs=inputs,
        cfg=cfg,
        mode=mode,
        arm=arm,
        end=end,
        hindsight_links=hindsight_links,
    )
    return result


def resume_replay(
    *,
    state: ReplayState,
    inputs: ReplayInputs,
    cfg: LabConfig,
    mode: ResearchMode,
    arm: Arm,
    end: datetime,
    hindsight_links: bool = False,
    checkpoint_at: datetime | None = None,
) -> tuple[ReplayResult, ReplayState]:
    """Continue a replay from ``state`` to ``end``.

    Returns the result over ``[state.start, end)`` — identical to
    ``run_replay`` over that window on the same inputs — and the state after
    the last tick before ``end``; or, with ``checkpoint_at``, the state after
    the last tick before ``checkpoint_at`` (which must not be after ``end``),
    so one pass can both report to ``end`` and leave a checkpoint behind it.

    ``inputs`` is the full input set, not just the new rows: the detectors
    read every visible row through the ``InformationState`` at each tick. What
    is saved is the ticks already folded into ``state``.

    The caller is responsible for the inputs visible at or before
    ``state.processed_until`` being the ones the state was built from —
    ``checkpoint.is_valid`` is that check. This function verifies only what
    it can see: the state's mode, arm, links mode, configuration and meme set.
    """
    if mode is ResearchMode.AUTHORITATIVE and hindsight_links:
        raise ValueError("AUTHORITATIVE mode refuses hindsight_links")
    if end <= state.start:
        raise ValueError("end must be after start")
    mismatch = _state_mismatch(
        state, inputs=inputs, cfg=cfg, mode=mode, arm=arm, hl=hindsight_links
    )
    if mismatch is not None:
        raise ValueError(f"replay state does not continue this replay: {mismatch}")
    if state.processed_until is not None and end <= state.processed_until:
        raise ValueError("the state is already at or past end")
    if checkpoint_at is not None and checkpoint_at > end:
        raise ValueError("checkpoint_at must not be after end")

    prepared = _prepare(inputs, mode)
    fingerprint = input_fingerprint(
        reprs=prepared.reprs,
        cfg=cfg,
        mode=mode,
        arm=arm,
        start=state.start,
        end=end,
        hindsight_links=hindsight_links,
        history_lookback=state.history_lookback,
    )
    fold = _Fold(state=state, prepared=prepared, cfg=cfg)

    interval = cfg.decision_interval
    first = state.start if state.processed_until is None else state.processed_until + interval
    exported: ReplayState | None = None
    for t in decision_times(first, end, interval) if first < end else []:
        if checkpoint_at is not None and exported is None and t >= checkpoint_at:
            exported = fold.export()
        fold.step(t)
    if exported is None:
        exported = fold.export()
    return fold.result(end=end, fingerprint=fingerprint), exported


def _canonical_meme_ids(inputs: ReplayInputs) -> tuple[str, ...]:
    return tuple(m.id for m in sorted(inputs.memes, key=lambda m: (m.id, _row_repr(m))))


def _state_mismatch(
    state: ReplayState,
    *,
    inputs: ReplayInputs,
    cfg: LabConfig,
    mode: ResearchMode,
    arm: Arm,
    hl: bool,
) -> str | None:
    if state.mode is not mode:
        return "mode"
    if state.arm is not arm:
        return "arm"
    if state.hindsight_links != hl:
        return "hindsight_links"
    if state.config_hash != config_hash(cfg, arm):
        return "config"
    if state.meme_ids != _canonical_meme_ids(inputs):
        return "meme_set"
    if tuple(m for m, _ in state.events) != state.meme_ids:
        return "events"
    return None


@dataclass(slots=True)
class _Prepared:
    reprs: dict[str, list[str]]
    mint_index: dict[str, _MintIndex]
    indexes: list[_MemeIndex]


def _prepare(inputs: ReplayInputs, mode: ResearchMode) -> _Prepared:
    """Canonicalise, then partition per meme and per mint, once per call."""
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

    if mode is ResearchMode.AUTHORITATIVE:
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
                    (obs_visibility_floor(o, mode), k, o)
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
    return _Prepared(reprs=reprs, mint_index=mint_index, indexes=indexes)


class _Fold:
    """One replay's working state: restored from a ``ReplayState``, advanced a
    tick at a time, exported back to one. The per-tick body is the replay."""

    def __init__(self, *, state: ReplayState, prepared: _Prepared, cfg: LabConfig) -> None:
        self.state0 = state
        self.cfg = cfg
        self.mode = state.mode
        self.arm = state.arm
        self.hindsight_links = state.hindsight_links
        self.lookback = state.history_lookback
        self.wired = strategy.is_wired(state.arm)
        self.mint_index = prepared.mint_index
        self.indexes = prepared.indexes
        for idx, (meme_id, events) in zip(self.indexes, state.events, strict=True):
            assert idx.meme.id == meme_id
            idx.events = list(events)

        self.portfolio = _Ledger(cfg.portfolio)
        self.portfolio.load(state)
        self.runtime: dict[str, _OpenRuntime] = {}
        for pos in state.open_positions:
            mi = self.mint_index.get(pos.trade.mint_address)
            self.runtime[pos.trade.trade_key] = _OpenRuntime(
                meme_id=pos.meme_id,
                exit_state=pos.exit_state,
                cursor=0 if mi is None else mi.visible_end(pos.cursor_at),
                cursor_at=pos.cursor_at,
                notes_seen=set(pos.notes_seen),
            )

        # The open runs are the only decision rows a later tick mutates
        # (``until``/``ticks``), so they are copied in: the state handed to
        # this fold is never written through.
        self.decision_log: list[dict[str, Any]] = list(state.decisions)
        self.open_index: dict[tuple[str, str], int] = {}
        self.last_outcome: dict[tuple[str, str], str] = {}
        for meme_id, mint, i, outcome in state.open_runs:
            self.decision_log[i] = dict(self.decision_log[i])
            self.open_index[(meme_id, mint)] = i
            self.last_outcome[(meme_id, mint)] = outcome
        self.rejection_counts: dict[str, int] = dict(state.rejection_counts)
        self.snapshots: list[PortfolioSnapshot] = list(state.snapshots)
        self.last_snapshot: PortfolioSnapshot | None = state.last_snapshot
        self.any_backfill = state.any_backfill
        self.ticks = state.ticks
        self.processed_until = state.processed_until

    # -- export / result -------------------------------------------------------

    def export(self) -> ReplayState:
        decisions = list(self.decision_log)
        open_runs: list[tuple[str, str, int, str]] = []
        for key in sorted(self.open_index):
            i = self.open_index[key]
            # A copy: this fold may keep extending the live row.
            decisions[i] = dict(decisions[i])
            open_runs.append((key[0], key[1], i, self.last_outcome[key]))
        positions: list[OpenPosition] = []
        for trade in self.portfolio.in_ledger_order():
            rt = self.runtime[trade.trade_key]
            positions.append(
                OpenPosition(
                    trade=trade,
                    meme_id=rt.meme_id,
                    exit_state=rt.exit_state,
                    cursor_at=rt.cursor_at,
                    notes_seen=tuple(sorted(rt.notes_seen)),
                )
            )
        s0 = self.state0
        return ReplayState(
            mode=s0.mode,
            arm=s0.arm,
            start=s0.start,
            hindsight_links=s0.hindsight_links,
            history_lookback=s0.history_lookback,
            config_hash=s0.config_hash,
            meme_ids=s0.meme_ids,
            ticks=self.ticks,
            processed_until=self.processed_until,
            cash=self.portfolio.cash,
            realized_pnl=self.portfolio.realized_pnl,
            peak_equity=self.portfolio.peak_equity,
            open_positions=tuple(positions),
            closed=tuple(self.portfolio.closed),
            snapshots=tuple(self.snapshots),
            last_snapshot=self.last_snapshot,
            events=tuple((idx.meme.id, tuple(idx.events)) for idx in self.indexes),
            decisions=tuple(decisions),
            open_runs=tuple(open_runs),
            rejection_counts=tuple(self.rejection_counts.items()),
            any_backfill=self.any_backfill,
        )

    def result(self, *, end: datetime, fingerprint: str) -> ReplayResult:
        """Assemble the result without disturbing the fold."""
        snapshots = list(self.snapshots)
        if self.ticks:
            # The closing point of the curve. The last tick's valuation is it:
            # nothing has changed since, so re-valuing (as an earlier version
            # did after the loop) gives the same numbers — and would move the
            # running peak, which a fold that continues must not do.
            last = self.last_snapshot
            assert last is not None and snapshots
            if snapshots[-1].at != last.at:
                snapshots.append(last)
        else:
            empty = _Ledger(self.cfg.portfolio)
            empty.load(self.state0)
            snapshots.append(empty.snapshot(self.state0.start, {}))

        open_at_end = self.portfolio.mark_end_of_data()
        trades = tuple(
            sorted(
                (*self.portfolio.closed, *open_at_end),
                key=lambda tr: (tr.entry_at, tr.trade_key),
            )
        )
        all_events = tuple(
            sorted((e for idx in self.indexes for e in idx.events), key=_event_sort_key)
        )
        metrics = compute_metrics(
            trades, snapshots, starting_capital=self.cfg.portfolio.starting_capital
        )
        return ReplayResult(
            mode=self.mode,
            arm=self.arm,
            start=self.state0.start,
            end=end,
            hindsight_links=self.hindsight_links,
            contains_backfill=self.any_backfill,
            input_fingerprint=fingerprint,
            ticks=self.ticks,
            trades=trades,
            snapshots=tuple(snapshots),
            events=all_events,
            decisions=tuple(dict(d) for d in self.decision_log),
            rejection_counts=dict(sorted(self.rejection_counts.items())),
            metrics=metrics,
            open_at_end=open_at_end,
        )

    # -- one tick --------------------------------------------------------------

    def log(
        self,
        t: datetime,
        meme_id: str,
        mint: str,
        outcome: tuple[Any, ...],
        row: dict[str, Any],
    ) -> None:
        key = (meme_id, mint)
        encoded = json.dumps(outcome, separators=(",", ":"))
        if self.last_outcome.get(key) == encoded and key in self.open_index:
            run = self.decision_log[self.open_index[key]]
            run["until"] = t.isoformat()
            run["ticks"] += 1
            return
        self.last_outcome[key] = encoded
        entry = {"at": t.isoformat(), "until": t.isoformat(), "ticks": 1, **row}
        self.open_index[key] = len(self.decision_log)
        self.decision_log.append(entry)

    def step(self, t: datetime) -> None:
        cfg = self.cfg
        mode = self.mode
        portfolio = self.portfolio
        runtime = self.runtime
        lo = _MIN_TIME if self.lookback is None else t - self.lookback
        # ---- phase 1: what was known about each meme ---------------------
        known: dict[str, _MemeTick] = {}
        for idx in self.indexes:
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
                hindsight_links=self.hindsight_links,
                max_observation_age=cfg.attention.max_observation_age,
            )
            self.any_backfill = self.any_backfill or state.contains_backfill
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
            mi = self.mint_index.get(trade.mint_address)
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
                    self.any_backfill = (
                        self.any_backfill or point.data_class is DataClass.BACKFILL
                    )
                    del runtime[trade.trade_key]
                    closed = True
                    break
            if closed:
                continue
            rt.cursor = end_i
            rt.cursor_at = t
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
                        self.any_backfill = (
                            self.any_backfill or latest.data_class is DataClass.BACKFILL
                        )
                        del runtime[trade.trade_key]
                        continue
            _annotate(portfolio, rt, trade.trade_key, notes, t)

        # ---- phase 3: entries --------------------------------------------
        for idx in self.indexes:
            mt = known[idx.meme.id]
            if not mt.market:
                self.log(
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
                    arm=self.arm,
                    wired=self.wired,
                    cfg=cfg,
                    meme_index=idx,
                    meme_tick=mt,
                    mint=mint,
                    mf=mf,
                    mint_index=self.mint_index.get(mint),
                    portfolio=portfolio,
                    runtime=runtime,
                    hindsight_links=self.hindsight_links,
                )
                if row.get("rejection"):
                    self.rejection_counts[row["rejection"]] = (
                        self.rejection_counts.get(row["rejection"], 0) + 1
                    )
                if row.get("entry_backfill"):
                    self.any_backfill = True
                row.pop("entry_backfill", None)
                outcome = (
                    row["status"],
                    row["reason_code"],
                    tuple(row["failed_conditions"]),
                    row["rejection"],
                    row["trade_key"],
                )
                self.log(t, idx.meme.id, mint, outcome, row)

        # ---- snapshot ----------------------------------------------------
        snap = portfolio.snapshot(t, _marks(portfolio, self.mint_index, t))
        if not self.snapshots or _snap_changed(self.snapshots[-1], snap):
            self.snapshots.append(snap)
        self.last_snapshot = snap
        self.ticks += 1
        self.processed_until = t


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
        cursor_at=t,
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
