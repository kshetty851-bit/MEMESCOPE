"""Meme Lifecycle Lab — orchestration: load → pure engines → persist / shape.

This module owns no rule. It reads through ``LifecycleLabRepository`` (all of
the Lab's SQL), hands rows to the pure engines, and either persists what they
return or shapes it into the API contract (docs/MEME_LIFECYCLE_LAB.md, "API
response contract"). It never commits: ``get_db`` owns an HTTP request's
transaction and ``scheduler.py`` owns a task's.

Conventions that are easy to break here:

* Every value shown on the radar or a detail page is evaluated by the engines
  at ``now`` in AUTHORITATIVE mode, through ``pit.information_available_at`` —
  the one gate. Nothing here computes a feature itself.
* A value that could not be measured is serialised as
  ``{"value": null, "unavailable_reason": ...}``, never ``0``. Series points are
  ``null`` for an hour nobody observed.
* Ratios leave as FRACTIONS (0.05 = 5%) — that is what the engines produce.
  The one exception at the source, ``PaperTrade.return_pct``, is a percent and
  is converted at this boundary (``_pct_fraction``).
* Prose is rendered here from stable reason codes. It describes what was
  observed; no string offers advice (``tests/unit/test_mll_wording.py``).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, cast

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.lifecycle_lab import attention as attention_engine
from app.lifecycle_lab import events as events_engine
from app.lifecycle_lab import experiments as experiments_engine
from app.lifecycle_lab import linking, pit, replay, strategy
from app.lifecycle_lab import market as market_engine
from app.lifecycle_lab import states as states_engine
from app.lifecycle_lab import timeliness as timeliness_engine
from app.lifecycle_lab.adapters import (
    AdapterError,
    AdapterResult,
    DexScreenerAdapter,
    GdeltAdapter,
    GeckoTerminalAdapter,
    SourceAdapter,
    Subject,
    WikipediaAdapter,
    build_adapters,
)
from app.lifecycle_lab.collector import collect_once
from app.lifecycle_lab.config import DEFAULT_CONFIG, LabConfig
from app.lifecycle_lab.domain import (
    ATTENTION_SOURCES,
    REAL_TRADING,
    TIMELINESS_HORIZONS,
    AliasKind,
    Arm,
    CollectionRun,
    DataClass,
    DivergenceCase,
    EventType,
    ExitReason,
    InformationState,
    LifecycleState,
    LinkMethod,
    MarketFeatures,
    MarketPoint,
    Measured,
    Meme,
    MemeAlias,
    MemeEvent,
    MemeTokenLink,
    Observation,
    ResearchMode,
    Source,
    SourceStatus,
    SplitSegment,
    TokenInfo,
    Unavailable,
)
from app.lifecycle_lab.portfolio import (
    STATUS_CLOSED,
    STATUS_OPEN,
    PaperTrade,
    PortfolioSnapshot,
)
from app.lifecycle_lab.replay import ReplayInputs, ReplayResult
from app.lifecycle_lab.repository import LifecycleLabRepository, normalize_alias

logger = get_logger(__name__)

HOUR = timedelta(hours=1)
DAY = timedelta(days=1)

#: Observation history the radar evaluates over: the 7-day attention baseline
#: plus a day. Revival / DEAD compare against longer history, so a radar row's
#: lifecycle state is "as far as the last 8 days show" — the same bound the
#: forward replay and forward detection use, so all three agree.
FORWARD_HISTORY_LOOKBACK = timedelta(days=8)
#: Market history the radar needs: 1h change + its reference window + slack.
RADAR_MARKET_LOOKBACK = timedelta(hours=3)
#: The detail chart's span.
DETAIL_LOOKBACK = timedelta(days=14)
#: Over-fetch below a lookback edge: a row's observed_at can precede its
#: retrieved_at by days (a Wikipedia day fetched later). The exact cut is made
#: on the replay's own keys afterwards.
LOAD_SLACK = timedelta(days=4)
#: An event's outcomes are settled this long after detection: the longest
#: horizon (24h) plus two hours for its reading to arrive.
OUTCOME_SETTLE_AFTER = max(TIMELINESS_HORIZONS) + timedelta(hours=2)
#: Readings before detection the timeliness engine looks at (1h lookback +
#: its tolerance).
OUTCOME_LOOKBACK = timedelta(hours=2)
#: Autolink budget per pass. DexScreener search is rate-limited and the
#: adapter spaces calls 0.5s apart; this keeps a pass well inside the task
#: time limit.
AUTOLINK_MAX_SEARCHES = 120
AUTOLINK_MAX_TERMS_PER_MEME = 6
LINKER_VERSION = "mll-linking-v1"
#: A meme row's whole forward run is one row per arm, re-saved by each replay.
FORWARD_SEGMENT = SplitSegment.ALL.value
AUTHORITATIVE = ResearchMode.AUTHORITATIVE.value

#: Arms the forward replay runs. Control A is registered but not wired (see
#: ``strategy.py``): replaying it would only produce ``not_wired`` rows.
REPLAY_ARMS: tuple[Arm, ...] = (
    Arm.BASELINE,
    Arm.CONTROL_B_MARKET_ONLY,
    Arm.CONTROL_C_ATTENTION_ONLY,
    Arm.CONTROL_D_COMBINED,
)
EXPERIMENT_ARMS: tuple[Arm, ...] = (*REPLAY_ARMS, Arm.CONTROL_A_EXISTING)

_ARM_SLUG: dict[Arm, str] = {
    Arm.BASELINE: "baseline",
    Arm.CONTROL_A_EXISTING: "control-a",
    Arm.CONTROL_B_MARKET_ONLY: "control-b",
    Arm.CONTROL_C_ATTENTION_ONLY: "control-c",
    Arm.CONTROL_D_COMBINED: "control-d",
}

HYPOTHESES: dict[Arm, str] = {
    Arm.BASELINE: (
        "A meme that already exists, observed in a new attention wave "
        "(attention acceleration over its own baseline) with market "
        "confirmation (1h volume growth), is followed by paper returns that "
        "differ from the market-only and attention-only control arms."
    ),
    Arm.CONTROL_A_EXISTING: (
        "Control A: MEMESCOPE's existing scoring over the same memes and "
        "period. Registered, not wired in Phase 1-4."
    ),
    Arm.CONTROL_B_MARKET_ONLY: "Control B: the market conditions alone, no attention.",
    Arm.CONTROL_C_ATTENTION_ONLY: "Control C: the attention conditions alone, no market.",
    Arm.CONTROL_D_COMBINED: (
        "Control D: attention and market conditions combined, registered "
        "separately from the baseline so the control table has a combined row."
    ),
}

SOURCE_LABELS: dict[Source, str] = {
    Source.PUMPFUN_REPLIES: "pump.fun replies",
    Source.WIKIPEDIA: "Wikipedia (daily pageviews)",
    Source.GDELT: "GDELT (news)",
    Source.DEXSCREENER: "DexScreener (token profiles)",
    Source.GECKOTERMINAL: "GeckoTerminal (OHLCV backfill)",
    Source.REDDIT: "Reddit",
    Source.X: "X",
}
#: Sources whose 24h volume is not in `mll_attention_observations`: pump.fun
#: replies are read in place, GeckoTerminal writes candles.
_NOT_COUNTED = frozenset({Source.PUMPFUN_REPLIES, Source.GECKOTERMINAL})

EVENT_LABELS: dict[EventType, str] = {
    EventType.ATTENTION_INCREASE: "Attention rose above its own baseline",
    EventType.ATTENTION_ACCELERATION: "Attention accelerated",
    EventType.MEME_REVIVAL: "Revival after an observed dormant period",
    EventType.NEW_ATTENTION_WAVE: "New attention wave",
    EventType.SECOND_WAVE: "Second attention wave",
    EventType.THIRD_WAVE: "Third or later attention wave",
    EventType.ATTENTION_DECAY: "Attention decayed from its wave peak",
    EventType.ATTENTION_PRICE_DIVERGENCE: "Attention up while price stayed flat",
    EventType.PRICE_ATTENTION_DIVERGENCE: "Price surged while attention fell",
    EventType.CROSS_PLATFORM_EXPANSION: "Attention spread to another platform",
}
EVENT_MARKER_KINDS: dict[EventType, str] = {
    EventType.ATTENTION_INCREASE: "attention_spike",
    EventType.ATTENTION_ACCELERATION: "attention_spike",
    EventType.MEME_REVIVAL: "revival",
    EventType.NEW_ATTENTION_WAVE: "wave",
    EventType.SECOND_WAVE: "wave",
    EventType.THIRD_WAVE: "wave",
    EventType.ATTENTION_DECAY: "decay",
    EventType.ATTENTION_PRICE_DIVERGENCE: "divergence",
    EventType.PRICE_ATTENTION_DIVERGENCE: "divergence",
    EventType.CROSS_PLATFORM_EXPANSION: "cross_platform",
}
EXIT_REASON_TEXT: dict[ExitReason, str] = {
    ExitReason.TAKE_PROFIT: "take-profit level reached",
    ExitReason.STOP_LOSS: "stop-loss level reached",
    ExitReason.TRAILING_STOP: "trailing stop reached",
    ExitReason.MAX_HOLD: "maximum time in position reached",
    ExitReason.ATTENTION_COLLAPSE: "attention collapsed below its level at entry",
    ExitReason.VOLUME_COLLAPSE: "1h volume collapsed below its level at entry",
    ExitReason.END_OF_DATA: "still open when the data ended (marked, not filled)",
}
ENTRY_REASON_TEXT: dict[str, str] = {
    strategy.REASON_CONDITIONS_MET: "every entry condition of the arm was met",
}
HORIZON_LABELS: dict[timedelta, str] = dict(
    zip(TIMELINESS_HORIZONS, ("5m", "15m", "30m", "1h", "2h", "6h", "24h"), strict=True)
)
_RETURN_COLUMNS: dict[str, str] = {
    label: f"return_{label}" for label in HORIZON_LABELS.values()
}

#: `enabled()` and `data_class` read settings only; the client is never touched.
_NO_CLIENT = cast("httpx.AsyncClient", None)


class LabNotFoundError(LookupError):
    """A meme slug or run id that does not exist."""


class LabConflictError(ValueError):
    """A curation request that collides with an existing record."""


class ExperimentSpecConflictError(ValueError):
    """An experiment key already registered under a different spec."""


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def parse_forward_start(raw: str | None = None) -> datetime | None:
    """``MLL_FORWARD_START`` as an aware UTC datetime; None if unset or invalid.

    A bare date is midnight UTC. Invalid is treated as unset (and logged):
    an epoch nobody can read must not start a verdict.
    """
    text = (settings.MLL_FORWARD_START if raw is None else raw).strip()
    if not text:
        return None
    try:
        if len(text) == 10:
            d = date.fromisoformat(text)
            return datetime(d.year, d.month, d.day, tzinfo=UTC)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("mll_forward_start_invalid", value=text)
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def autolink_min_confidence() -> Decimal | None:
    try:
        value = Decimal(str(settings.MLL_AUTOLINK_MIN_CONFIDENCE).strip())
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() and Decimal(0) < value <= Decimal(1) else None


def _dec_str(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if not value.is_finite():
        return None
    # Normalised so a NUMERIC(24,4) reads "1000", not "1000.0000"; "f" so it
    # never becomes "1E+3".
    text = format(value.normalize(), "f")
    return "0" if text in ("-0", "") else text


def measured(
    value: Measured | Decimal | None, *, missing: str = "unavailable"
) -> dict[str, Any]:
    """The contract's Measured object. ``None`` is not 0 either."""
    if isinstance(value, Unavailable):
        return {"value": None, "unavailable_reason": value.reason}
    if value is None:
        return {"value": None, "unavailable_reason": missing}
    return {"value": _dec_str(value), "unavailable_reason": None}


def _level(value: Measured | None) -> str | None:
    return _dec_str(value) if isinstance(value, Decimal) else None


def _pct_fraction(value: Decimal | None) -> Decimal | None:
    """``PaperTrade.return_pct`` is a percent; the API speaks fractions."""
    return None if value is None else value / Decimal(100)


def _floor(t: datetime, step: timedelta) -> datetime:
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    return epoch + ((t - epoch) // step) * step


def _ceil(t: datetime, step: timedelta) -> datetime:
    floored = _floor(t, step)
    return floored if floored == t else floored + step


def sample_label(n_trades: int) -> str:
    label = experiments_engine.sample_label(n_trades)
    if label == experiments_engine.INSUFFICIENT_SAMPLE:
        return f"insufficient (<{experiments_engine.MIN_TRADES})"
    floor = next(f for f, name in experiments_engine.CONFIDENCE_STEPS if name == label)
    return f"{label.lower().replace('_', ' ')} ({floor}+)"


def experiment_key(forward_start: datetime, arm: Arm) -> str:
    return f"mll-forward-{forward_start:%Y%m%dT%H%M%SZ}-{_ARM_SLUG[arm]}"


def primary_link(links: Iterable[MemeTokenLink]) -> MemeTokenLink | None:
    """Highest confidence; ties to the earliest link, then the mint."""
    ordered = sorted(links, key=lambda k: (-k.confidence, k.linked_at, k.mint_address))
    return ordered[0] if ordered else None


def exit_reason_text(code: str | None) -> str | None:
    if code is None:
        return None
    try:
        return EXIT_REASON_TEXT[ExitReason(code)]
    except (KeyError, ValueError):
        return code.replace("_", " ")


def entry_reason_text(code: str) -> str:
    return ENTRY_REASON_TEXT.get(code, code.replace("_", " "))


def event_label(code: str) -> str:
    try:
        return EVENT_LABELS[EventType(code)]
    except (KeyError, ValueError):
        return code.replace("_", " ")


def _detail_value(value: Any) -> str:
    if isinstance(value, dict) and "unavailable" in value:
        return f"unavailable ({value['unavailable']})"
    return "unavailable" if value is None else str(value)


def timeline_text(kind: str, detail: Any) -> str:
    """Prose for one evidence-timeline item, from its stable kind code."""
    d = detail if isinstance(detail, dict) else {}
    if kind == "meme_tracking_started":
        return "Tracking of this meme started"
    if kind == "link_created":
        return (
            f"Token linked ({d.get('method', 'unknown method')}, "
            f"confidence {d.get('confidence', 'unknown')})"
        )
    if kind == "token_created":
        return "Token created"
    if kind == "first_market_reading":
        return f"First market reading, price {_detail_value(d.get('price_usd'))}"
    if kind == "entry_price_reading":
        return (
            f"Price reading used for the paper entry: {_detail_value(d.get('price_usd'))} "
            f"({d.get('data_class', 'forward')})"
        )
    if kind == "entry":
        return f"Paper entry: {entry_reason_text(str(d.get('reason_code', '')))}"
    if kind == "exit_check_unavailable":
        return f"An exit rule could not be checked: {_detail_value(detail)}"
    if kind.startswith("exit:"):
        return f"Paper exit: {exit_reason_text(kind.removeprefix('exit:'))}"
    if kind.startswith("event:"):
        return f"Event observed: {event_label(kind.removeprefix('event:'))}"
    return kind.replace("_", " ")


def _event_from_row(row: Mapping[str, Any]) -> MemeEvent | None:
    try:
        return MemeEvent(
            meme_id=str(row["meme_id"]),
            event_type=EventType(row["event_type"]),
            detected_at=row["detected_at"],
            mode=ResearchMode(row["mode"]),
            detector_version=row["detector_version"],
            mint_address=row["mint_address"],
            divergence_case=(
                DivergenceCase(row["divergence_case"]) if row["divergence_case"] else None
            ),
            lifecycle_state=(
                LifecycleState(row["lifecycle_state"]) if row["lifecycle_state"] else None
            ),
            features=dict(row["features"] or {}),
            contains_backfill=bool(row["contains_backfill"]),
        )
    except ValueError:
        # A vocabulary this build does not know (a newer detector): not a
        # prior this detector can reason about.
        return None


def _event_sort_key(e: MemeEvent) -> tuple[str, str, str, str]:
    # The replay's own order, so forward detection accumulates identically.
    return (e.detected_at.isoformat(), e.meme_id, e.event_type.value, e.mint_address or "")


def _trade_row(t: PaperTrade) -> dict[str, Any]:
    return {
        "trade_key": t.trade_key,
        "arm": t.arm.value,
        "meme_id": t.meme_id,
        "mint_address": t.mint_address,
        "entry_at": t.entry_at,
        "entry_price": t.entry_price,
        "size_usd": t.size_usd,
        "quantity": t.quantity,
        "entry_fees_usd": t.entry_fees_usd,
        "entry_market_cap": t.entry_market_cap,
        "entry_liquidity_usd": t.entry_liquidity_usd,
        "token_age_seconds": t.token_age_seconds,
        "age_bucket": t.age_bucket.value,
        "lifecycle_state": t.lifecycle_state.value,
        "divergence_case": t.divergence_case.value,
        "entry_reason": t.entry_reason,
        "entry_features": t.entry_features,
        "evidence_timeline": list(t.evidence_timeline),
        "cost_model": t.cost_model,
        "exit_at": t.exit_at,
        "exit_price": t.exit_price,
        "exit_reason": None if t.exit_reason is None else t.exit_reason.value,
        "exit_fees_usd": t.exit_fees_usd,
        "pnl_usd": t.pnl_usd,
        "return_pct": t.return_pct,
        "status": t.status,
        "contains_backfill": t.contains_backfill,
        "hindsight": t.hindsight,
    }


def _snapshot_row(s: PortfolioSnapshot) -> dict[str, Any]:
    return {
        "at": s.at,
        "equity": s.equity,
        "cash": s.cash,
        "deployed": s.deployed,
        "realized_pnl": s.realized_pnl,
        "unrealized_pnl": s.unrealized_pnl,
        "open_positions": s.open_positions,
        "peak_equity": s.peak_equity,
        "drawdown": s.drawdown,
    }


def trade_out(row: Mapping[str, Any]) -> dict[str, Any]:
    """A stored paper trade in the contract's shape."""
    timeline = row.get("evidence_timeline") or []
    return {
        "trade_key": row["trade_key"],
        "arm": row["arm"],
        "mint": row["mint_address"],
        "entry_at": row["entry_at"],
        "entry_price": _dec_str(row["entry_price"]),
        "size_usd": _dec_str(row["size_usd"]),
        "exit_at": row["exit_at"],
        "exit_price": _dec_str(row["exit_price"]),
        "exit_reason": row["exit_reason"],
        "exit_reason_text": exit_reason_text(row["exit_reason"]),
        "pnl_usd": _dec_str(row["pnl_usd"]),
        "return_pct": _dec_str(_pct_fraction(row["return_pct"])),
        "status": row["status"],
        "entry_reason": entry_reason_text(row["entry_reason"]),
        "evidence_timeline": [
            {
                "at": item.get("at"),
                "kind": str(item.get("kind", "")),
                "detail": timeline_text(str(item.get("kind", "")), item.get("detail")),
            }
            for item in timeline
            if isinstance(item, dict)
        ],
        "contains_backfill": bool(row.get("contains_backfill", False)),
    }


@dataclass(frozen=True, slots=True)
class _MemeInputs:
    meme: Meme
    aliases: tuple[MemeAlias, ...]
    links: tuple[MemeTokenLink, ...]
    tokens: tuple[TokenInfo, ...]
    observations: tuple[Observation, ...]
    market: tuple[MarketPoint, ...]
    runs: tuple[CollectionRun, ...]

    def state(self, as_of: datetime, mode: ResearchMode, cfg: LabConfig) -> InformationState:
        return pit.information_available_at(
            as_of=as_of,
            mode=mode,
            meme=self.meme,
            aliases=self.aliases,
            links=self.links,
            tokens=self.tokens,
            observations=self.observations,
            market=self.market,
            runs=self.runs,
            max_observation_age=cfg.attention.max_observation_age,
        )


def partition(inputs: ReplayInputs) -> list[_MemeInputs]:
    """Per-meme slices, so the gate is not handed every other meme's rows."""
    out: list[_MemeInputs] = []
    for meme in sorted(inputs.memes, key=lambda m: m.id):
        links = tuple(k for k in inputs.links if k.meme_id == meme.id)
        mints = {k.mint_address for k in links}
        out.append(
            _MemeInputs(
                meme=meme,
                aliases=tuple(a for a in inputs.aliases if a.meme_id == meme.id),
                links=links,
                tokens=tuple(t for t in inputs.tokens if t.mint_address in mints),
                observations=tuple(
                    o
                    for o in inputs.observations
                    if o.meme_id == meme.id or (o.meme_id is None and o.mint_address in mints)
                ),
                market=tuple(p for p in inputs.market if p.mint_address in mints),
                runs=tuple(
                    r
                    for r in inputs.runs
                    if r.meme_id == meme.id
                    or (
                        r.meme_id is None
                        and (r.mint_address is None or r.mint_address in mints)
                    )
                ),
            )
        )
    return out


class _BackfillAdapter:
    """Runs an adapter's ``backfill`` through the collector, so a backfill is
    recorded exactly like any other collection: one run per attempt."""

    data_class: DataClass = DataClass.BACKFILL

    def __init__(
        self, inner: WikipediaAdapter | GdeltAdapter, start: datetime, end: datetime
    ) -> None:
        self.source: Source = inner.source
        self._inner = inner
        self._start = start
        self._end = end

    def enabled(self) -> tuple[bool, str | None]:
        return self._inner.enabled()

    async def collect(self, subjects: Sequence[Subject], *, now: datetime) -> AdapterResult:
        return await self._inner.backfill(subjects[0], self._start, self._end, now)


# --------------------------------------------------------------------------
# The service
# --------------------------------------------------------------------------


class LifecycleLabService:
    def __init__(self, session: AsyncSession, *, cfg: LabConfig = DEFAULT_CONFIG) -> None:
        self.session = session
        self.repo = LifecycleLabRepository(session)
        self.cfg = cfg

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    async def load_inputs(
        self,
        *,
        meme_ids: Sequence[str] | None,
        until: datetime,
        since: datetime | None,
        include_backfill: bool,
        market_since: datetime | None = None,
    ) -> ReplayInputs:
        """Raw rows for tracked memes (all, or ``meme_ids``), visible by
        ``until`` at the repository's over-fetching bound. The precise cut is
        the gate's."""
        memes = await self.repo.tracked_memes()
        if meme_ids is not None:
            wanted = set(meme_ids)
            memes = [m for m in memes if m.id in wanted]
        return await self._load(
            memes,
            until=until,
            since=since,
            include_backfill=include_backfill,
            market_since=market_since,
        )

    async def _load(
        self,
        memes: Sequence[Meme],
        *,
        until: datetime,
        since: datetime | None,
        include_backfill: bool,
        market_since: datetime | None = None,
    ) -> ReplayInputs:
        ids = [m.id for m in memes]
        if not ids:
            return ReplayInputs(memes=())
        aliases = await self.repo.aliases_for(ids)
        links = await self.repo.links_for(ids)
        mints = sorted({k.mint_address for k in links})
        tokens = await self.repo.tokens(mints)
        observations = await self.repo.observations(
            meme_ids=ids, mints=mints, until=until, since=since
        )
        if not include_backfill:
            observations = [o for o in observations if o.data_class is DataClass.FORWARD]
        market = await self.repo.market_points(
            mints,
            since=since if market_since is None else market_since,
            until=until,
            include_backfill=include_backfill,
        )
        runs = await self.repo.runs(meme_ids=ids, since=since, until=until)
        if not include_backfill:
            runs = [r for r in runs if r.data_class is DataClass.FORWARD]
        return ReplayInputs(
            memes=tuple(memes),
            aliases=tuple(aliases),
            links=tuple(links),
            tokens=tuple(tokens),
            observations=tuple(observations),
            market=tuple(market),
            runs=tuple(runs),
        )

    async def _capped_memes(self) -> tuple[list[Meme], bool]:
        memes = await self.repo.tracked_memes()
        cap = max(0, settings.MLL_MAX_TRACKED_TOKENS)
        return memes[:cap], len(memes) > cap

    # ------------------------------------------------------------------
    # Source health
    # ------------------------------------------------------------------

    async def _sources(self, now: datetime) -> list[dict[str, Any]]:
        adapters = {a.source: a for a in build_adapters(settings, _NO_CLIENT)}
        latest: dict[Source, CollectionRun] = {}
        # Global run first (the sweep), per-subject run as a fallback.
        for seen in await self.repo.latest_runs_by_source():
            latest.setdefault(seen.source, seen)
        counts = await self.repo.observation_counts(since=now - DAY)
        stale_after = self.cfg.attention.max_observation_age
        out: list[dict[str, Any]] = []
        for source in sorted(Source, key=lambda s: s.value):
            adapter = adapters[source]
            enabled, why = adapter.enabled()
            run = latest.get(source)
            status: str
            reason: str | None
            if not enabled:
                status, reason = SourceStatus.DISABLED.value, why or "disabled_by_config"
            elif run is None:
                status, reason = pit.NEVER_COLLECTED, pit.NEVER_COLLECTED
            elif (
                run.status is SourceStatus.AVAILABLE
                and adapter.data_class is DataClass.FORWARD
                and now - run.finished_at > stale_after
            ):
                status, reason = SourceStatus.STALE.value, pit.STALE_REASON
            else:
                status, reason = run.status.value, run.reason
            countable = status not in (SourceStatus.DISABLED.value, pit.NEVER_COLLECTED)
            out.append(
                {
                    "source": source.value,
                    "label": SOURCE_LABELS[source],
                    "status": status,
                    "reason": reason,
                    "last_run_at": None if run is None else run.finished_at,
                    "data_class": adapter.data_class.value,
                    "observations_24h": (
                        counts.get(source.value, 0)
                        if countable and source not in _NOT_COUNTED
                        else None
                    ),
                }
            )
        return out

    async def health(self, now: datetime) -> dict[str, Any]:
        return {"generated_at": now, "sources": await self._sources(now)}

    # ------------------------------------------------------------------
    # Experiments
    # ------------------------------------------------------------------

    def _pending_note(self, data_cutoff: datetime) -> str:
        return (
            f"{experiments_engine.SPLIT_NOTE_INSUFFICIENT_FORWARD}: no segment is "
            f"out-of-sample until the planned data cutoff ({data_cutoff.isoformat()}) "
            "has passed"
        )

    async def ensure_baseline_experiment(self, now: datetime) -> dict[Arm, str]:
        """Register the pre-registered experiment set; returns ids by arm.

        The split covers ``[forward_start, forward_start +
        MLL_EXPERIMENT_HORIZON_DAYS)`` and is fixed when first registered:
        the insert is ``ON CONFLICT DO NOTHING`` and the spec hash covers the
        boundaries, so changing the horizon or the config later is refused
        (``ExperimentSpecConflictError``) instead of quietly moving the goalposts.

        ``split_meaningful`` stays False until the planned data cutoff has
        passed, then becomes True only with enough closed trades.
        """
        fs = parse_forward_start()
        if fs is None:
            return {}
        end = fs + timedelta(days=settings.MLL_EXPERIMENT_HORIZON_DAYS)
        ids: dict[Arm, str] = {}
        for arm in EXPERIMENT_ARMS:
            spec = experiments_engine.build_experiment(
                experiment_key=experiment_key(fs, arm),
                hypothesis=HYPOTHESES[arm],
                created_at=now,
                start=fs,
                end=end,
                cfg=self.cfg,
                mode=ResearchMode.AUTHORITATIVE,
                arm=arm,
                forward_start=fs,
            )
            wired = strategy.is_wired(arm)
            values = {
                "experiment_key": spec.experiment_key,
                "hypothesis": spec.hypothesis,
                "data_cutoff": spec.data_cutoff,
                "train_start": spec.train_start,
                "train_end": spec.train_end,
                "validation_start": spec.validation_start,
                "validation_end": spec.validation_end,
                "test_start": spec.test_start,
                "test_end": spec.test_end,
                # Strategy AND config: the run is reproducible from this row.
                "strategy_spec": {"strategy": spec.strategy_spec, "config": spec.config_spec},
                "spec_hash": spec.spec_hash,
                "mode": spec.mode.value,
                "arm": arm.value,
                "status": "registered" if wired else "not_wired",
                "split_meaningful": False,
                "split_note": self._pending_note(spec.data_cutoff),
                "notes": None if wired else strategy.REASON_CONTROL_A_NOT_WIRED,
            }
            try:
                ids[arm] = await self.repo.upsert_experiment(values)
            except ValueError as exc:
                raise ExperimentSpecConflictError(str(exc)) from exc

        # Split status: re-derived from the clock and the trade count, never
        # from new boundaries.
        for row in await self.repo.list_experiments():
            if row["id"] not in ids.values():
                continue
            cutoff = row["data_cutoff"]
            meaningful: bool = False
            note: str | None = self._pending_note(cutoff)
            if cutoff is not None and now >= cutoff:
                run = await self.repo.latest_run(mode=AUTHORITATIVE, experiment_id=row["id"])
                n = 0 if run is None else int(run["trades_count"])
                if n >= experiments_engine.MIN_TRADES:
                    meaningful, note = True, None
                else:
                    note = experiments_engine.SPLIT_NOTE_INSUFFICIENT_TRADES
            if (row["split_meaningful"], row["split_note"]) != (meaningful, note):
                await self.repo.update_experiment(
                    row["id"], {"split_meaningful": meaningful, "split_note": note}
                )
        return ids

    def _experiment_out(self, row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "experiment_key": row["experiment_key"],
            "hypothesis": row["hypothesis"],
            "arm": row["arm"],
            "mode": row["mode"],
            "spec_hash": row["spec_hash"],
            "created_at": row["created_at"],
            "data_cutoff": row["data_cutoff"],
            "train": [row["train_start"], row["train_end"]],
            "validation": [row["validation_start"], row["validation_end"]],
            "test": [row["test_start"], row["test_end"]],
            "split_meaningful": bool(row["split_meaningful"]),
            "split_note": row["split_note"],
            "status": row["status"],
        }

    async def experiments(self) -> dict[str, Any]:
        rows = await self.repo.list_experiments()
        return {"items": [self._experiment_out(r) for r in rows]}

    async def _baseline_experiment(self) -> dict[str, Any] | None:
        fs = parse_forward_start()
        if fs is None:
            return None
        return await self.repo.get_experiment_by_key(experiment_key(fs, Arm.BASELINE))

    async def _baseline_run(self) -> dict[str, Any] | None:
        experiment = await self._baseline_experiment()
        if experiment is None:
            return None
        return await self.repo.latest_run(mode=AUTHORITATIVE, experiment_id=experiment["id"])

    # ------------------------------------------------------------------
    # Overview
    # ------------------------------------------------------------------

    async def overview(self, now: datetime) -> dict[str, Any]:
        fs = parse_forward_start()
        experiment = await self._baseline_experiment()
        run = (
            None
            if experiment is None
            else await self.repo.latest_run(mode=AUTHORITATIVE, experiment_id=experiment["id"])
        )
        memes = await self.repo.tracked_memes()
        links = await self.repo.links_for([m.id for m in memes])
        linked = {k.mint_address for k in links if k.visible_at(now)}

        starting = self.cfg.portfolio.starting_capital
        portfolio: dict[str, Any] = {
            "run_id": None,
            "as_of": None,
            "starting_capital": _dec_str(starting),
            "equity": None,
            "cash": None,
            "deployed": None,
            "realized_pnl": None,
            "unrealized_pnl": None,
            "roi": None,
            "drawdown": None,
            "trades": 0,
            "open_positions": 0,
            "sample_label": sample_label(0),
            "unavailable_reason": (
                "forward_start_not_set" if fs is None else "no_forward_run_yet"
            ),
        }
        if run is not None:
            summary = run.get("summary") or {}
            metrics = summary.get("metrics") or {}
            final = summary.get("final_snapshot") or {}
            trades = int(metrics.get("trades", run["trades_count"]) or 0)
            portfolio.update(
                run_id=run["id"],
                as_of=run["window_end"],
                equity=final.get("equity"),
                cash=final.get("cash"),
                deployed=final.get("deployed"),
                realized_pnl=final.get("realized_pnl"),
                unrealized_pnl=final.get("unrealized_pnl"),
                # Fractions, as the metrics engine computes them.
                roi=metrics.get("roi"),
                drawdown=metrics.get("max_drawdown"),
                trades=trades,
                open_positions=int(final.get("open_positions") or 0),
                sample_label=sample_label(trades),
                unavailable_reason=None,
            )

        notes = ["Paper only: the Lab never places a real trade."]
        if fs is None:
            notes.insert(
                0,
                "MLL_FORWARD_START is not set: no forward data counts toward a verdict yet.",
            )
        else:
            notes.insert(
                0,
                f"Only forward data collected since {fs.isoformat()} counts toward "
                "the verdict.",
            )
        return {
            "lab_enabled": bool(settings.FEATURE_LIFECYCLE_LAB_ENABLED),
            "real_trading": REAL_TRADING,
            "mode": AUTHORITATIVE,
            "forward_start": fs,
            "forward_days": (
                None
                if fs is None
                else round(max(0.0, (now - fs).total_seconds() / 86400.0), 2)
            ),
            "portfolio": portfolio,
            "experiment": (
                None
                if experiment is None
                else {
                    "experiment_key": experiment["experiment_key"],
                    "split_meaningful": bool(experiment["split_meaningful"]),
                    "split_note": experiment["split_note"],
                    "train": [experiment["train_start"], experiment["train_end"]],
                    "validation": [
                        experiment["validation_start"],
                        experiment["validation_end"],
                    ],
                    "test": [experiment["test_start"], experiment["test_end"]],
                }
            ),
            "sources": await self._sources(now),
            "tracked_memes": len(memes),
            "linked_tokens": len(linked),
            "notes": notes,
        }

    # ------------------------------------------------------------------
    # Radar
    # ------------------------------------------------------------------

    async def memes(self, now: datetime) -> dict[str, Any]:
        inputs = await self.load_inputs(
            meme_ids=None,
            until=now,
            since=now - FORWARD_HISTORY_LOOKBACK,
            market_since=now - RADAR_MARKET_LOOKBACK,
            include_backfill=False,
        )
        prior = await self._prior_events(
            [m.id for m in inputs.memes], since=now - FORWARD_HISTORY_LOOKBACK - DAY
        )
        paper: dict[str, str] = {}
        run = await self._baseline_run()
        if run is not None:
            for row in await self.repo.trades_for_run(run["id"]):
                mid = str(row["meme_id"])
                if row["status"] == STATUS_OPEN:
                    paper[mid] = "open"
                elif row["status"] == STATUS_CLOSED:
                    paper.setdefault(mid, "closed")
        rows = [
            self._radar_row(mi, now, prior.get(mi.meme.id, ()), paper.get(mi.meme.id, "none"))
            for mi in partition(inputs)
        ]
        rows.sort(key=lambda r: r["slug"])
        return {"generated_at": now, "items": rows}

    async def _prior_events(
        self, meme_ids: Sequence[str], *, since: datetime
    ) -> dict[str, tuple[MemeEvent, ...]]:
        out: dict[str, list[MemeEvent]] = {}
        for row in await self.repo.recent_events(meme_ids, mode=AUTHORITATIVE, since=since):
            event = _event_from_row(row)
            if event is not None:
                out.setdefault(event.meme_id, []).append(event)
        return {k: tuple(sorted(v, key=_event_sort_key)) for k, v in out.items()}

    def _radar_row(
        self,
        mi: _MemeInputs,
        now: datetime,
        prior: Sequence[MemeEvent],
        paper_status: str,
    ) -> dict[str, Any]:
        state = mi.state(now, ResearchMode.AUTHORITATIVE, self.cfg)
        attn = attention_engine.attention_features(state, self.cfg.attention)
        primary = primary_link(state.links)
        mf: MarketFeatures | None = (
            None
            if primary is None
            else market_engine.market_features(state, primary.mint_address)
        )
        lifecycle = states_engine.classify_state(
            state=state, attention=attn, market=mf, prior_events=prior, cfg=self.cfg.events
        )
        tokens = {t.mint_address: t for t in state.tokens}
        newest: list[datetime] = [o.retrieved_at for o in state.observations]
        if primary is not None:
            newest.extend(
                p.observed_at for p in state.market if p.mint_address == primary.mint_address
            )
        no_token = Unavailable("no_linked_token")
        return {
            "slug": mi.meme.slug,
            "display_name": mi.meme.display_name,
            "tokens": [
                {
                    "mint": k.mint_address,
                    "symbol": tokens[k.mint_address].symbol
                    if k.mint_address in tokens
                    else None,
                    "name": tokens[k.mint_address].name if k.mint_address in tokens else None,
                    "link_method": k.method.value,
                    "confidence": _dec_str(k.confidence),
                    "linked_at": k.linked_at,
                }
                for k in state.links
            ],
            "primary_mint": None if primary is None else primary.mint_address,
            "token_age_seconds": (
                None
                if mf is None or mf.token_age is None
                else int(mf.token_age.total_seconds())
            ),
            "age_bucket": "unknown" if mf is None else mf.age_bucket.value,
            "market_cap": None if mf is None else _level(mf.market_cap),
            "liquidity_usd": None if mf is None else _level(mf.liquidity_usd),
            "volume_1h": None if mf is None else _level(mf.volume_1h),
            "price_change_1h": None if mf is None else _level(mf.price_change),
            "attention": {
                "mentions_1h": measured(attn.mentions_1h),
                "mentions_24h": measured(attn.mentions_24h),
                "velocity": measured(attn.velocity),
                "acceleration": measured(attn.acceleration),
                "baseline_multiple": measured(attn.baseline_multiple),
                "platform_count": measured(attn.platform_count),
            },
            "lifecycle_state": lifecycle.value,
            "market_activity": measured(no_token if mf is None else mf.volume_growth),
            "data_freshness_seconds": (
                int((now - max(newest)).total_seconds()) if newest else None
            ),
            "paper_status": paper_status,
            "contains_backfill": state.contains_backfill,
        }

    # ------------------------------------------------------------------
    # Detail
    # ------------------------------------------------------------------

    async def meme_detail(
        self, slug: str, now: datetime, *, include_backfill: bool = False
    ) -> dict[str, Any] | None:
        record = await self.repo.meme_record(slug)
        meme = await self.repo.get_meme_by_slug(slug)
        if record is None or meme is None:
            return None
        since = now - DETAIL_LOOKBACK
        mode = ResearchMode.EXPLORATORY if include_backfill else ResearchMode.AUTHORITATIVE
        inputs = await self._load(
            [meme], until=now, since=since, include_backfill=include_backfill
        )
        mi = partition(inputs)[0]
        state = mi.state(now, mode, self.cfg)
        primary = primary_link(state.links)

        # ---- series ------------------------------------------------------
        attention_points = attention_engine.attention_series(state, bucket=HOUR)
        primary_points = (
            []
            if primary is None
            else [p for p in state.market if p.mint_address == primary.mint_address]
        )
        earliest = [meme.tracking_started_at]
        earliest.extend(t for t, _ in attention_points[:1])
        earliest.extend(p.observed_at for p in primary_points[:1])
        start = max(_floor(since, HOUR), _floor(min(earliest), HOUR))
        end = _floor(now, HOUR)
        grid: list[datetime] = []
        at = start
        while at < end:
            grid.append(at)
            at += HOUR

        def on_grid(points: Iterable[tuple[datetime, Measured]]) -> list[dict[str, Any]]:
            values = dict(points)
            return [{"t": t, "value": _level(values.get(t))} for t in grid]

        per_source: dict[str, list[dict[str, Any]]] = {}
        for source in sorted(ATTENTION_SOURCES, key=lambda s: s.value):
            only = replace(
                state, observations=tuple(o for o in state.observations if o.source is source)
            )
            series = attention_engine.attention_series(only, bucket=HOUR)
            if series:
                per_source[source.value] = on_grid(series)

        price, volume = self._market_series(primary_points, grid)

        backfill_before: datetime | None = None
        contains_backfill = bool(include_backfill and state.contains_backfill)
        if contains_backfill:
            ends = [
                o.window_end or o.observed_at
                for o in state.observations
                if o.data_class is DataClass.BACKFILL
            ]
            ends.extend(
                p.observed_at for p in state.market if p.data_class is DataClass.BACKFILL
            )
            backfill_before = _ceil(max(ends), HOUR) if ends else None

        # ---- events, trades, markers --------------------------------------
        event_rows = await self.repo.events_for_meme(
            meme.id, mode=None if include_backfill else AUTHORITATIVE, limit=200
        )
        run = await self._baseline_run()
        trade_rows = (
            []
            if run is None
            else await self.repo.trades_for_meme(meme.id, backtest_run_id=run["id"])
        )
        markers = self._markers(event_rows, trade_rows, state)

        return {
            "meme": {
                "slug": record["slug"],
                "display_name": record["display_name"],
                "description": record["description"],
                "tracking_started_at": record["tracking_started_at"],
                "wikipedia_title": record["wikipedia_title"],
                "gdelt_query": record["gdelt_query"],
            },
            "aliases": [
                {"alias": a.alias, "kind": a.kind.value, "added_at": a.added_at}
                for a in mi.aliases
                if a.added_at <= now
            ],
            "links": [
                {
                    "mint": k.mint_address,
                    "method": k.method.value,
                    "confidence": _dec_str(k.confidence),
                    "linked_at": k.linked_at,
                    "unlinked_at": k.unlinked_at,
                }
                for k in mi.links
            ],
            "series": {
                "attention": on_grid(attention_points),
                "price": price,
                "volume": volume,
                "per_source": per_source,
                "backfill_before": backfill_before,
            },
            "markers": markers,
            "events": [self._event_out(r) for r in event_rows],
            "trades": [trade_out(r) for r in trade_rows],
            "data_label": "exploratory" if contains_backfill else AUTHORITATIVE,
            "contains_backfill": contains_backfill,
            "sources": await self._sources(now),
        }

    @staticmethod
    def _market_series(
        points: Sequence[MarketPoint], grid: Sequence[datetime]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Last price per hour; volume = last forward ``volume_1h`` in the hour,
        else the sum of backfilled sub-hour bars inside it. ``null`` where the
        hour had no reading — never 0."""
        by_hour: dict[datetime, list[MarketPoint]] = {}
        for p in points:
            # A bar is stamped at its close; it describes the hour it started in.
            described = p.observed_at - timedelta(seconds=p.bar_seconds or 0)
            by_hour.setdefault(_floor(described, HOUR), []).append(p)
        price: list[dict[str, Any]] = []
        volume: list[dict[str, Any]] = []
        for t in grid:
            hour = sorted(
                by_hour.get(t, []), key=lambda p: (p.observed_at, p.available_at, p.source)
            )
            priced = [p for p in hour if p.price_usd is not None]
            price.append({"t": t, "value": _dec_str(priced[-1].price_usd) if priced else None})
            forward = [p for p in hour if p.volume_1h is not None]
            vol: Decimal | None = None
            if forward:
                vol = forward[-1].volume_1h
            else:
                bars = [
                    p.bar_volume
                    for p in hour
                    if p.bar_volume is not None
                    and p.bar_seconds is not None
                    and p.bar_seconds <= 3600
                ]
                if bars:
                    vol = sum(bars, Decimal(0))
            volume.append({"t": t, "value": _dec_str(vol)})
        return price, volume

    @staticmethod
    def _event_out(row: Mapping[str, Any]) -> dict[str, Any]:
        reasons = row.get("outcome_reasons") or {}
        complete = row.get("outcomes_complete_at") is not None
        has_mint = row.get("mint_address") is not None

        def outcome(column: str) -> dict[str, Any]:
            value = row.get(column)
            if value is not None:
                return measured(value)
            if not has_mint:
                return measured(Unavailable("no_linked_token"))
            if column in reasons:
                return measured(Unavailable(str(reasons[column])))
            return measured(Unavailable("unavailable" if complete else "not_measured_yet"))

        return {
            "event_type": row["event_type"],
            "label": event_label(row["event_type"]),
            "detected_at": row["detected_at"],
            "mint": row["mint_address"],
            "divergence_case": row["divergence_case"],
            "lifecycle_state": row["lifecycle_state"],
            "mode": row["mode"],
            "contains_backfill": bool(row["contains_backfill"]),
            "returns": {label: outcome(col) for label, col in _RETURN_COLUMNS.items()},
            "price_at_detection": _dec_str(row.get("price_at_detection")),
            "run_up_before_detection": outcome("run_up_before_detection"),
        }

    @staticmethod
    def _markers(
        events: Sequence[Mapping[str, Any]],
        trades: Sequence[Mapping[str, Any]],
        state: InformationState,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for e in events:
            try:
                kind = EVENT_MARKER_KINDS[EventType(e["event_type"])]
            except (KeyError, ValueError):
                kind = "event"
            out.append(
                {
                    "t": e["detected_at"],
                    "kind": kind,
                    "label": event_label(e["event_type"]),
                    "event_type": e["event_type"],
                    "mint": e["mint_address"],
                }
            )
        for t in trades:
            out.append(
                {
                    "t": t["entry_at"],
                    "kind": "paper_entry",
                    "label": f"Paper entry ({entry_reason_text(t['entry_reason'])})",
                    "event_type": None,
                    "mint": t["mint_address"],
                }
            )
            if t["status"] == STATUS_CLOSED and t["exit_at"] is not None:
                out.append(
                    {
                        "t": t["exit_at"],
                        "kind": "paper_exit",
                        "label": f"Paper exit: {exit_reason_text(t['exit_reason'])}",
                        "event_type": None,
                        "mint": t["mint_address"],
                    }
                )
        for token in state.tokens:
            if token.created_at is not None:
                out.append(
                    {
                        "t": token.created_at,
                        "kind": "token_launch",
                        "label": f"Token created: {token.symbol or token.mint_address[:6]}",
                        "event_type": None,
                        "mint": token.mint_address,
                    }
                )
        for link in state.links:
            out.append(
                {
                    "t": link.linked_at,
                    "kind": "token_linked",
                    "label": f"Token linked ({link.method.value})",
                    "event_type": None,
                    "mint": link.mint_address,
                }
            )
        out.sort(key=lambda m: (m["t"], m["kind"], m["mint"] or ""))
        return out

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    async def run_detail(self, run_id: str) -> dict[str, Any] | None:
        try:
            uuid.UUID(str(run_id))
        except ValueError:
            return None
        run = await self.repo.get_run(run_id)
        if run is None:
            return None
        summary = run.get("summary") or {}
        metrics = dict(summary.get("metrics") or {})
        # return_pct percentiles are percents at the source; the API speaks
        # fractions everywhere.
        percentiles = metrics.get("return_percentiles")
        if isinstance(percentiles, dict):
            metrics["return_percentiles"] = {
                k: None if v is None else _dec_str(Decimal(str(v)) / Decimal(100))
                for k, v in percentiles.items()
            }
        snapshots = await self.repo.snapshots_for_run(run_id)
        trades = await self.repo.trades_for_run(run_id)
        return {
            "run": {
                "id": run["id"],
                "experiment_id": run["experiment_id"],
                "arm": summary.get("arm"),
                "mode": run["mode"],
                "segment": run["segment"],
                "status": run["status"],
                "started_at": run["started_at"],
                "finished_at": run["finished_at"],
                "window_start": run["window_start"],
                "window_end": run["window_end"],
                "input_fingerprint": run["input_fingerprint"],
                "trades_count": run["trades_count"],
                "ending_equity": _dec_str(run["ending_equity"]),
                "contains_backfill": run["contains_backfill"],
                "hindsight_links": run["hindsight_links"],
                "error": run["error"],
                "duration_seconds": summary.get("duration_seconds"),
                "recompute": summary.get("recompute"),
            },
            "metrics": metrics,
            "snapshots": [
                {
                    "at": s["at"],
                    "equity": _dec_str(s["equity"]),
                    "cash": _dec_str(s["cash"]),
                    "deployed": _dec_str(s["deployed"]),
                    "realized_pnl": _dec_str(s["realized_pnl"]),
                    "unrealized_pnl": _dec_str(s["unrealized_pnl"]),
                    "open_positions": s["open_positions"],
                    "peak_equity": _dec_str(s["peak_equity"]),
                    "drawdown": _dec_str(s["drawdown"]),
                }
                for s in snapshots
            ],
            "trades": [trade_out(t) for t in trades],
        }

    # ------------------------------------------------------------------
    # Forward replay
    # ------------------------------------------------------------------

    async def run_forward_replay(self, now: datetime) -> dict[str, Any]:
        """AUTHORITATIVE replay over ``[forward_start, now)`` per wired arm,
        persisted into ONE forward run row per arm.

        Recomputes from scratch every time: the replay is deterministic, and
        point-in-time gating means a later run cannot change what an earlier
        tick saw, so re-saving is idempotent — trades upsert their exit side
        only, snapshots and events are first-write-wins. Cost grows with the
        forward period (ticks x memes x arms); ``FORWARD_HISTORY_LOOKBACK``
        bounds each tick's history and ``MLL_MAX_TRACKED_TOKENS`` caps the
        memes. Incremental replay is a later optimisation.
        """
        fs = parse_forward_start()
        if fs is None:
            return {"skipped": "forward_start_not_set"}
        if now <= fs:
            return {"skipped": "forward_not_started"}
        ids = await self.ensure_baseline_experiment(now)
        memes, capped = await self._capped_memes()
        inputs = await self._load(
            memes,
            until=now,
            since=fs - FORWARD_HISTORY_LOOKBACK,
            include_backfill=False,
        )
        out: dict[str, Any] = {"memes": len(memes), "capped": capped, "runs": {}}
        for arm in REPLAY_ARMS:
            began = time.monotonic()
            result = replay.run_replay(
                inputs=inputs,
                cfg=self.cfg,
                mode=ResearchMode.AUTHORITATIVE,
                arm=arm,
                start=fs,
                end=now,
                history_lookback=FORWARD_HISTORY_LOOKBACK,
            )
            run_id = await self._persist_forward(
                experiment_id=ids[arm],
                result=result,
                now=now,
                memes=len(memes),
                capped=capped,
                duration=time.monotonic() - began,
            )
            out["runs"][arm.value] = {
                "run_id": run_id,
                "trades": result.metrics.trades,
                "ticks": result.ticks,
            }
        return out

    async def _persist_forward(
        self,
        *,
        experiment_id: str,
        result: ReplayResult,
        now: datetime,
        memes: int,
        capped: bool,
        duration: float,
    ) -> str:
        existing = await self.repo.find_run(
            experiment_id=experiment_id, mode=AUTHORITATIVE, segment=FORWARD_SEGMENT
        )
        if existing is None:
            run_id = await self.repo.save_run(
                {
                    "experiment_id": experiment_id,
                    "mode": AUTHORITATIVE,
                    "segment": FORWARD_SEGMENT,
                    "status": "running",
                    "started_at": now,
                    "window_start": result.start,
                    "window_end": result.end,
                    "config_spec": self.cfg.as_spec(),
                }
            )
        else:
            run_id = str(existing["id"])
        await self.repo.save_trades(run_id, [_trade_row(t) for t in result.trades])
        await self.repo.save_snapshots(run_id, [_snapshot_row(s) for s in result.snapshots])
        if result.arm is Arm.BASELINE:
            # Events do not depend on the arm; one copy is enough.
            await self.repo.save_events(result.events, source_run_id=run_id)
        final = result.snapshots[-1]
        await self.repo.update_run(
            run_id,
            {
                "status": "completed",
                "finished_at": now,
                "window_end": result.end,
                "trades_count": result.metrics.trades,
                "ending_equity": final.equity,
                "contains_backfill": result.contains_backfill,
                "input_fingerprint": result.input_fingerprint,
                "error": None,
                "summary": {
                    "arm": result.arm.value,
                    "metrics": result.metrics.to_dict(),
                    "final_snapshot": final.to_dict(),
                    "rejection_counts": result.rejection_counts,
                    "ticks": result.ticks,
                    "decision_runs": len(result.decisions),
                    "events": len(result.events),
                    "open_at_end": [t.trade_key for t in result.open_at_end],
                    "memes": memes,
                    "memes_capped": capped,
                    "history_lookback_seconds": FORWARD_HISTORY_LOOKBACK.total_seconds(),
                    "recompute": "full",
                    "duration_seconds": round(duration, 3),
                },
            },
        )
        return run_id

    # ------------------------------------------------------------------
    # Forward detection and outcomes
    # ------------------------------------------------------------------

    async def detect_and_store_events(self, now: datetime) -> dict[str, Any]:
        """Detect at the last decision-grid instant ``<= now``.

        Aligned to the replay's epoch grid and given the same history bound,
        so a forward detection and the forward replay's detection at the same
        instant are the same event row (deduplicated by the identity index)
        rather than two near-copies a few seconds apart.
        """
        interval = self.cfg.decision_interval
        t = _floor(now, interval)
        lo = t - FORWARD_HISTORY_LOOKBACK
        memes, _ = await self._capped_memes()
        inputs = await self._load(
            memes, until=t, since=lo - LOAD_SLACK, include_backfill=False
        )
        prior = await self._prior_events([m.id for m in memes], since=lo - DAY)
        new: list[MemeEvent] = []
        for mi in partition(inputs):
            # The replay's slice: rows whose knowledge time is in [lo, t].
            window = replace(
                mi,
                observations=tuple(o for o in mi.observations if o.retrieved_at >= lo),
                market=tuple(p for p in mi.market if p.available_at >= lo),
                runs=tuple(r for r in mi.runs if r.finished_at >= lo),
            )
            state = window.state(t, ResearchMode.AUTHORITATIVE, self.cfg)
            attn = attention_engine.attention_features(state, self.cfg.attention)
            mkt = [
                market_engine.market_features(state, m)
                for m in sorted({k.mint_address for k in state.links})
            ]
            acc = list(prior.get(mi.meme.id, ()))
            for mf in mkt if mkt else [None]:
                fired = sorted(
                    events_engine.detect_events(
                        state=state,
                        attention=attn,
                        market=mf,
                        prior_events=tuple(acc),
                        cfg=self.cfg.events,
                    ),
                    key=_event_sort_key,
                )
                acc.extend(fired)
                new.extend(fired)
        saved = await self.repo.save_events(new)
        return {"at": t.isoformat(), "memes": len(memes), "detected": len(new), "new": saved}

    async def fill_timeliness(self, now: datetime) -> dict[str, Any]:
        """Measure outcomes for events whose horizons have settled.

        An event is measured once, ``OUTCOME_SETTLE_AFTER`` after detection,
        over readings up to that instant — so the outcome does not depend on
        when this task happened to run. Unavailable outcomes are stored as
        NULL with their reason. Look-ahead by design: this never feeds a
        decision (see ``timeliness.py``).
        """
        rows = await self.repo.events_awaiting_outcomes(
            detected_before=now - OUTCOME_SETTLE_AFTER
        )
        by_mint: dict[tuple[str, bool], list[Mapping[str, Any]]] = {}
        for row in rows:
            backfill = row["mode"] != AUTHORITATIVE
            by_mint.setdefault((row["mint_address"], backfill), []).append(row)
        recorded = 0
        for (mint, backfill), events in sorted(by_mint.items()):
            first = min(e["detected_at"] for e in events)
            last = max(e["detected_at"] for e in events)
            points = await self.repo.market_points(
                [mint],
                since=first - OUTCOME_LOOKBACK,
                until=last + OUTCOME_SETTLE_AFTER,
                include_backfill=backfill,
            )
            for e in events:
                cutoff = e["detected_at"] + OUTCOME_SETTLE_AFTER
                result = timeliness_engine.timeliness(
                    detected_at=e["detected_at"],
                    mint_address=mint,
                    points=[p for p in points if p.observed_at <= cutoff],
                )
                await self.repo.record_timeliness(e["id"], result, complete_at=now)
                recorded += 1
        return {"recorded": recorded}

    # ------------------------------------------------------------------
    # Linking
    # ------------------------------------------------------------------

    async def autolink(
        self,
        now: datetime,
        dexscreener: DexScreenerAdapter,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> dict[str, Any]:
        """Search DexScreener for each meme's names and link a candidate only
        at ``confidence >= MLL_AUTOLINK_MIN_CONFIDENCE``.

        At the default 0.8 that means a WEBSITE or SOCIAL handle the token's
        own profile points at. Name (0.6) and ticker (0.5) matches are left to
        manual curation: many tokens share a ticker, and a false link admits
        that token's market into the meme's history. A meme with no DOMAIN or
        SOCIAL_HANDLE alias therefore cannot be autolinked and is not searched.

        ``linked_at`` is ``now`` — the server clock when the link is made,
        never the token's creation time or anything earlier.
        """
        floor = autolink_min_confidence()
        if floor is None:
            return {"skipped": "invalid_min_confidence"}
        finish = clock or (lambda: now)
        memes, _ = await self._capped_memes()
        ids = [m.id for m in memes]
        aliases = await self.repo.aliases_for(ids)
        links = await self.repo.links_for(ids)
        anchors = {AliasKind.DOMAIN, AliasKind.SOCIAL_HANDLE}
        searches = created = 0
        blocked: str | None = None
        for meme in memes:
            known = [a for a in aliases if a.meme_id == meme.id and a.added_at <= now]
            if not any(a.kind in anchors for a in known):
                continue
            terms = list(
                dict.fromkeys(
                    t
                    for t in [meme.display_name]
                    + [a.alias for a in known if a.kind in (AliasKind.NAME, AliasKind.SYMBOL)]
                    if linking.normalise(t)
                )
            )[:AUTOLINK_MAX_TERMS_PER_MEME]
            linked = {k.mint_address for k in links if k.meme_id == meme.id}
            status, reason = SourceStatus.AVAILABLE, None
            meme_searches = meme_links = 0
            for term in terms:
                if blocked is not None:
                    status, reason = SourceStatus.ERROR, blocked
                    break
                if searches >= AUTOLINK_MAX_SEARCHES:
                    status, reason = SourceStatus.PARTIAL, "deferred_budget"
                    break
                searches += 1
                meme_searches += 1
                try:
                    candidates = await dexscreener.search_candidates(term, now=now)
                except AdapterError as exc:
                    status, reason = SourceStatus.ERROR, exc.reason
                    if exc.reason == "rate_limited":
                        blocked = exc.reason
                    break
                for token, profile in candidates:
                    if token.mint_address in linked:
                        continue
                    matches = linking.match_token(
                        meme=meme, aliases=known, token=token, profile=profile, now=now
                    )
                    strong = [m for m in matches if m.confidence >= floor]
                    if not strong:
                        continue
                    evidence = {
                        "search_term": term,
                        "methods": [m.method.value for m in matches],
                        "token_name": token.name,
                        "token_symbol": token.symbol,
                        "websites": profile.get("websites"),
                        "socials": profile.get("socials"),
                        "matcher": LINKER_VERSION,
                    }
                    link = replace(strong[0], linked_at=now)
                    if await self.repo.add_link(
                        link, evidence=evidence, linked_by=f"autolink:{LINKER_VERSION}"
                    ):
                        created += 1
                        meme_links += 1
                        linked.add(token.mint_address)
            await self.repo.record_run(
                CollectionRun(
                    id=str(uuid.uuid4()),
                    source=Source.DEXSCREENER,
                    status=status,
                    started_at=now,
                    finished_at=finish(),
                    data_class=DataClass.FORWARD,
                    reason=reason,
                    meme_id=meme.id,
                    detail={
                        "purpose": "autolink_search",
                        "searches": meme_searches,
                        "links_created": meme_links,
                        "min_confidence": str(floor),
                    },
                )
            )
        return {"searches": searches, "links_created": created, "blocked": blocked}

    # ------------------------------------------------------------------
    # Collection
    # ------------------------------------------------------------------

    async def subjects(self, now: datetime) -> list[Subject]:
        """Tracked memes, their aliases known by ``now``, and their links
        visible at ``now`` that are inside the tracked-token budget."""
        memes = await self.repo.tracked_memes()
        ids = [m.id for m in memes]
        aliases = await self.repo.aliases_for(ids)
        links = await self.repo.links_for(ids)
        budget = set(await self.repo.current_linked_mints())
        return [
            Subject(
                meme=m,
                aliases=tuple(a for a in aliases if a.meme_id == m.id and a.added_at <= now),
                mints=tuple(
                    sorted(
                        {
                            k.mint_address
                            for k in links
                            if k.meme_id == m.id
                            and k.visible_at(now)
                            and k.mint_address in budget
                        }
                    )
                ),
            )
            for m in memes
        ]

    async def collect(
        self,
        now: datetime,
        adapters: Sequence[SourceAdapter],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> list[CollectionRun]:
        """One FORWARD pass. BACKFILL-class adapters (GeckoTerminal OHLCV) are
        not part of the schedule: they are one-off and run from ``backfill``."""
        forward = [a for a in adapters if a.data_class is DataClass.FORWARD]
        if not forward:
            return []
        subjects = await self.subjects(now)
        return await collect_once(
            repo=self.repo, adapters=forward, subjects=subjects, now=now, clock=clock
        )

    @staticmethod
    def build_adapters(client: httpx.AsyncClient) -> list[SourceAdapter]:
        return build_adapters(settings, client)

    async def backfill(
        self,
        slug: str,
        now: datetime,
        start: datetime,
        end: datetime,
        client: httpx.AsyncClient,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> list[CollectionRun]:
        """EXPLORATORY history for one meme: Wikipedia + GDELT over
        ``[start, end]`` and GeckoTerminal OHLCV for its linked mints, all
        stamped BACKFILL (``retrieved_at = now``) and recorded as runs. None of
        it can reach an AUTHORITATIVE result."""
        if not (start < end <= now):
            raise ValueError("backfill window must satisfy start < end <= now")
        meme = await self.repo.get_meme_by_slug(slug)
        if meme is None:
            raise LabNotFoundError(slug)
        aliases = [a for a in await self.repo.aliases_for([meme.id]) if a.added_at <= now]
        mints = sorted(
            {k.mint_address for k in await self.repo.links_for([meme.id]) if k.visible_at(now)}
        )
        subject = Subject(meme=meme, aliases=tuple(aliases), mints=tuple(mints))
        adapters: list[SourceAdapter] = []
        for adapter in build_adapters(settings, client):
            if isinstance(adapter, WikipediaAdapter | GdeltAdapter):
                adapters.append(_BackfillAdapter(adapter, start, end))
            elif isinstance(adapter, GeckoTerminalAdapter):
                adapters.append(adapter)
        return await collect_once(
            repo=self.repo,
            adapters=adapters,
            subjects=[subject],
            now=now,
            data_class=DataClass.BACKFILL,
            clock=clock,
        )

    # ------------------------------------------------------------------
    # Curation (admin)
    # ------------------------------------------------------------------

    async def get_meme(self, slug: str) -> Meme | None:
        return await self.repo.get_meme_by_slug(slug)

    async def create_meme(
        self,
        *,
        slug: str,
        display_name: str,
        now: datetime,
        description: str | None = None,
        wikipedia_title: str | None = None,
        gdelt_query: str | None = None,
        aliases: Sequence[tuple[str, AliasKind]] = (),
    ) -> dict[str, Any]:
        """``tracking_started_at`` and every alias's ``added_at`` are the
        server's ``now``: nothing about this meme is FORWARD data before it."""
        # The unique index is the guarantee; this check only keeps a duplicate
        # from poisoning the request's transaction with an IntegrityError.
        if await self.repo.get_meme_by_slug(slug) is not None:
            raise LabConflictError(f"meme {slug!r} already exists")
        meme = await self.repo.create_meme(
            slug=slug,
            display_name=display_name,
            tracking_started_at=now,
            wikipedia_title=wikipedia_title,
            gdelt_query=gdelt_query,
            description=description,
        )
        added = []
        for alias, kind in aliases:
            row = await self.repo.add_alias(meme.id, alias, kind, now)
            if row is not None:
                added.append(
                    {"alias": row.alias, "kind": row.kind.value, "added_at": row.added_at}
                )
        return {
            "slug": meme.slug,
            "display_name": meme.display_name,
            "description": description,
            "tracking_started_at": meme.tracking_started_at,
            "wikipedia_title": meme.wikipedia_title,
            "gdelt_query": meme.gdelt_query,
            "aliases": added,
        }

    async def add_alias(
        self, slug: str, alias: str, kind: AliasKind, now: datetime
    ) -> dict[str, Any]:
        meme = await self.repo.get_meme_by_slug(slug)
        if meme is None:
            raise LabNotFoundError(slug)
        row = await self.repo.add_alias(meme.id, alias, kind, now)
        if row is not None:
            return {
                "alias": row.alias,
                "kind": row.kind.value,
                "added_at": row.added_at,
                "created": True,
            }
        # Already known: report the moment it FIRST became known.
        key = normalize_alias(alias)
        for existing in await self.repo.aliases_for([meme.id]):
            if existing.kind is kind and normalize_alias(existing.alias) == key:
                return {
                    "alias": existing.alias,
                    "kind": existing.kind.value,
                    "added_at": existing.added_at,
                    "created": False,
                }
        raise LabConflictError("alias normalises to nothing")

    async def add_manual_link(
        self, slug: str, mint: str, confidence: Decimal, actor: str, now: datetime
    ) -> dict[str, Any]:
        """A curated link. ``linked_at`` is the server's ``now`` — a client can
        never date a link, because a link dated before a pump is exactly the
        look-ahead the Lab exists to exclude."""
        meme = await self.repo.get_meme_by_slug(slug)
        if meme is None:
            raise LabNotFoundError(slug)
        link = MemeTokenLink(
            meme_id=meme.id,
            mint_address=mint,
            method=LinkMethod.MANUAL,
            confidence=confidence,
            linked_at=now,
        )
        created = await self.repo.add_link(
            link, evidence={"actor": actor}, linked_by=f"manual:{actor}"
        )
        stored = next(
            k for k in await self.repo.links_for([meme.id]) if k.mint_address == mint
        )
        return {
            "mint": stored.mint_address,
            "method": stored.method.value,
            "confidence": _dec_str(stored.confidence),
            "linked_at": stored.linked_at,
            "unlinked_at": stored.unlinked_at,
            "created": created,
        }
