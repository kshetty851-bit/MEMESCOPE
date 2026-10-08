"""Meme Lifecycle Lab — incremental replay is the replay.

``resume_replay`` exists so the forward replay does not re-run every past tick
every 30 minutes. It is only allowed to exist if it is *invisible*: for the
same inputs, a replay stopped anywhere and continued must produce exactly what
the uninterrupted replay produces — events, entries, exits, the equity curve,
the decision log, the metrics and the input fingerprint. These tests stop it
in the places where carried state is most likely to be lost or duplicated:
inside an open position (exit cursor, running peak, evidence notes), inside an
attention episode (prior events, re-arm memory), on the tick an exit fires,
after every single tick, and with backfilled rows in EXPLORATORY mode.

If one of these fails, the engine is wrong. Do not weaken the comparison.

The synthetic world is deliberately busy: several memes with first, second
and third attention waves, an observed dormancy and a revival, a link made
mid-replay, a link withdrawn mid-replay, a mint shared by two memes, unpriced
market readings, a market-wide volume surge that hits the five-position cap,
and price paths that end in take-profit, stop-loss, volume-collapse,
attention-collapse and max-hold exits.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.lifecycle_lab.config import EventConfig, ExitConfig, LabConfig, PortfolioConfig
from app.lifecycle_lab.domain import (
    AliasKind,
    Arm,
    CollectionRun,
    DataClass,
    EventType,
    ExitReason,
    LinkMethod,
    MarketPoint,
    Meme,
    MemeAlias,
    MemeTokenLink,
    Metric,
    Observation,
    ResearchMode,
    Source,
    SourceStatus,
    TokenInfo,
    ValueKind,
)
from app.lifecycle_lab.replay import (
    ReplayInputs,
    ReplayResult,
    ReplayState,
    decision_times,
    resume_replay,
    run_replay,
)

pytestmark = pytest.mark.unit

H0 = datetime(2026, 8, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)
BUCKET = timedelta(minutes=15)
STEP = timedelta(minutes=5)
AUTH = ResearchMode.AUTHORITATIVE
EXPL = ResearchMode.EXPLORATORY

#: A faster grid, a shorter dormancy and hold, three slots instead of five so
#: a handful of memes can fill the book, and a trailing stop so the running
#: peak carried across ticks matters. Equivalence depends on none of these.
CFG = LabConfig(
    decision_interval=timedelta(minutes=15),
    events=EventConfig(dormant_for=timedelta(hours=10)),
    exits=ExitConfig(max_hold=timedelta(hours=10), trailing_stop_fraction=Decimal("0.3")),
    portfolio=PortfolioConfig(max_open_positions=3, max_deployed=Decimal(30)),
)

START = H0 + timedelta(hours=25)
END = H0 + timedelta(hours=64)


def _mid(i: int) -> str:
    return f"meme-{i:02d}"


def _mint(i: int, k: int = 0) -> str:
    return f"MINT{i:02d}{'ABCDEFGH'[k]}"


def _waves(i: int) -> list[tuple[float, float, int]]:
    """(start hour, length in hours, mentions per 15-min bucket)."""
    o = (i * 2.25) % 9
    if i % 5 == 4:
        # Busy early, then an observed dormancy (measured zeros), then a
        # revival — the MEME_REVIVAL path.
        return [(26 + o, 4, 9), (32 + o, 12, 0), (44 + o, 3, 14)]
    return [
        (27 + o, 3, 10),
        (40 + o, 2, 14),
        (55 + o, 3, 22),
    ]


def _mentions(i: int, t: datetime) -> int | None:
    hours = (t - H0) / HOUR
    if i % 3 == 2 and 37 <= hours < 38:
        return None  # nobody was watching: a gap, not a zero
    for start, length, level in _waves(i):
        if start <= hours < start + length:
            return level
    return 1 + (int(hours) + i) % 2


def _price(i: int, k: int, t: datetime) -> Decimal | None:
    hours = (t - H0) / HOUR
    n = int((t - H0) / STEP)
    if (n + i) % 37 == 0:
        return None  # an unpriced reading
    base = Decimal(1) + Decimal((n * 7 + i * 3) % 11) / Decimal(1000)
    w1, w2, w3 = (w[0] for w in _waves(i))
    kind = (i + k) % 5
    for w in (w1, w2, w3):
        if w + 1 <= hours < w + 6:
            if kind == 0:
                return base * Decimal("2.5")  # take profit
            if kind == 1:
                return base * Decimal("0.4")  # stop loss
            if kind == 3:
                # Up, then back: the trailing stop reads the carried peak.
                return base * (Decimal("1.6") if hours < w + 2.5 else Decimal("1.05"))
    return base


def _volume(i: int, k: int, t: datetime) -> Decimal:
    hours = (t - H0) / HOUR
    kind = (i + k) % 5
    for start, _length, level in _waves(i):
        if level and start + 0.25 <= hours < start + 2:
            return Decimal(3200)
        if kind == 2 and level and start + 2 <= hours < start + 6:
            return Decimal(150)  # volume collapse
    if 56 <= hours < 57.5:
        return Decimal(4000)  # a market-wide surge: more entries than slots
    return Decimal(1000)


def world(
    n_memes: int = 5,
    *,
    hours: int = 80,
    backfill: bool = False,
) -> ReplayInputs:
    end = H0 + timedelta(hours=hours)
    memes: list[Meme] = []
    aliases: list[MemeAlias] = []
    links: list[MemeTokenLink] = []
    tokens: list[TokenInfo] = []
    obs: list[Observation] = []
    market: list[MarketPoint] = []
    runs: list[CollectionRun] = []

    for i in range(n_memes):
        mid = _mid(i)
        memes.append(Meme(id=mid, slug=mid, display_name=f"Meme {i}", tracking_started_at=H0))
        aliases.append(MemeAlias(mid, f"meme{i}", AliasKind.NAME, H0))
        mints = [_mint(i)]
        if i == 0:
            mints.append(_mint(0, 1))
        for k, m in enumerate(mints):
            linked_at = H0
            if i == 0 and k == 1:
                linked_at = H0 + timedelta(hours=46, minutes=3)  # mid-replay link
            if i == 5:
                linked_at = H0 + timedelta(hours=34, minutes=7)
            unlinked_at = H0 + timedelta(hours=60) if i == 1 else None
            links.append(
                MemeTokenLink(
                    meme_id=mid,
                    mint_address=m,
                    method=LinkMethod.MANUAL,
                    confidence=Decimal("0.9"),
                    linked_at=linked_at,
                    unlinked_at=unlinked_at,
                )
            )
            tokens.append(
                TokenInfo(
                    mint_address=m,
                    name=f"Meme {i}",
                    symbol=f"M{i}",
                    created_at=H0 - timedelta(days=3 + i),
                    discovered_at=H0 - timedelta(days=3 + i),
                )
            )
            t = H0
            while t < end:
                market.append(
                    MarketPoint(
                        mint_address=m,
                        observed_at=t,
                        available_at=t + timedelta(seconds=30),
                        data_class=DataClass.FORWARD,
                        price_usd=_price(i, k, t),
                        market_cap=Decimal(50_000 + 1000 * i),
                        liquidity_usd=Decimal(80_000) if (i + k) % 2 else None,
                        volume_1h=_volume(i, k, t),
                    )
                )
                t += STEP
        t = H0
        while t < end:
            close = t + BUCKET
            value = _mentions(i, t)
            if value is not None:
                obs.append(
                    Observation(
                        source=Source.GDELT,
                        metric=Metric.MENTIONS,
                        value_kind=ValueKind.WINDOW_COUNT,
                        data_class=DataClass.FORWARD,
                        source_timestamp=t,
                        observed_at=close,
                        retrieved_at=close + timedelta(minutes=2, seconds=i),
                        raw_value=Decimal(value),
                        meme_id=mid,
                        window_start=t,
                        window_end=close,
                        query=f"meme {i}",
                    )
                )
            t = close
        if i == 3:
            # A meme-specific failure: GDELT is unavailable for this meme
            # until the next sweep finishes.
            runs.append(
                CollectionRun(
                    id=f"err-{mid}",
                    source=Source.GDELT,
                    status=SourceStatus.ERROR,
                    started_at=H0 + timedelta(hours=50, minutes=2),
                    finished_at=H0 + timedelta(hours=50, minutes=3),
                    data_class=DataClass.FORWARD,
                    reason="http_500",
                    meme_id=mid,
                )
            )

    # A mint shared by two memes (meme 2 and meme 3 both claim meme 2's mint).
    if n_memes > 3:
        links.append(
            MemeTokenLink(
                meme_id=_mid(3),
                mint_address=_mint(2),
                method=LinkMethod.EXACT_SYMBOL,
                confidence=Decimal("0.8"),
                linked_at=H0 + timedelta(hours=30),
            )
        )

    t = H0
    while t < end:
        close = t + BUCKET
        runs.append(
            CollectionRun(
                id=f"gdelt-{close.isoformat()}",
                source=Source.GDELT,
                status=SourceStatus.AVAILABLE,
                started_at=close + timedelta(minutes=1),
                finished_at=close + timedelta(minutes=2, seconds=30),
                data_class=DataClass.FORWARD,
            )
        )
        t = close

    if backfill:
        # Exploratory history before tracking began, fetched long after.
        fetched = end + timedelta(days=20)
        for i in range(min(n_memes, 3)):
            t = H0 - timedelta(days=2)
            while t < H0 + timedelta(hours=30):
                close = t + BUCKET
                obs.append(
                    Observation(
                        source=Source.GDELT,
                        metric=Metric.MENTIONS,
                        value_kind=ValueKind.WINDOW_COUNT,
                        data_class=DataClass.BACKFILL,
                        source_timestamp=t,
                        observed_at=close,
                        retrieved_at=fetched,
                        raw_value=Decimal(2 + (i % 2)),
                        meme_id=_mid(i),
                        window_start=t,
                        window_end=close,
                        query=f"meme {i} backfill",
                    )
                )
                t = close
            t = H0 - timedelta(days=1)
            while t < H0 + timedelta(hours=34):
                close = t + HOUR
                market.append(
                    MarketPoint(
                        mint_address=_mint(i),
                        observed_at=close,
                        available_at=close,
                        data_class=DataClass.BACKFILL,
                        price_usd=Decimal("0.98") + Decimal(i) / 100,
                        market_cap=Decimal(40_000),
                        bar_volume=Decimal(900 + 10 * i),
                        bar_seconds=3600,
                        source="geckoterminal",
                    )
                )
                t = close

    return ReplayInputs(
        memes=tuple(memes),
        aliases=tuple(aliases),
        links=tuple(links),
        tokens=tuple(tokens),
        observations=tuple(obs),
        market=tuple(market),
        runs=tuple(runs),
    )


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def result_digest(r: ReplayResult) -> str:
    """One hash over everything a result says."""
    return hashlib.sha256(
        json.dumps(r.to_dict(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def assert_same(full: ReplayResult, other: ReplayResult) -> None:
    """Piece by piece first, so a failure names what diverged."""
    assert other.ticks == full.ticks
    assert [e.__repr__() for e in other.events] == [e.__repr__() for e in full.events]
    assert [t.to_dict() for t in other.trades] == [t.to_dict() for t in full.trades]
    assert [t.trade_key for t in other.open_at_end] == [t.trade_key for t in full.open_at_end]
    assert [s.to_dict() for s in other.snapshots] == [s.to_dict() for s in full.snapshots]
    assert list(other.decisions) == list(full.decisions)
    assert other.rejection_counts == full.rejection_counts
    assert other.metrics == full.metrics
    assert other.contains_backfill == full.contains_backfill
    assert other.input_fingerprint == full.input_fingerprint
    assert other == full
    assert result_digest(other) == result_digest(full)


def initial(
    inputs: ReplayInputs,
    *,
    arm: Arm = Arm.BASELINE,
    mode: ResearchMode = AUTH,
    start: datetime = START,
    hindsight_links: bool = False,
    history_lookback: timedelta | None = None,
    cfg: LabConfig = CFG,
) -> ReplayState:
    return ReplayState.initial(
        inputs=inputs,
        cfg=cfg,
        mode=mode,
        arm=arm,
        start=start,
        hindsight_links=hindsight_links,
        history_lookback=history_lookback,
    )


def chained(
    inputs: ReplayInputs,
    cuts: list[datetime],
    *,
    arm: Arm = Arm.BASELINE,
    mode: ResearchMode = AUTH,
    end: datetime = END,
    hindsight_links: bool = False,
    history_lookback: timedelta | None = None,
    round_trip: bool = True,
) -> tuple[ReplayResult, ReplayState]:
    """Replay [START, end) stopping at each cut; every intermediate state goes
    through JSON, as a checkpoint would."""
    state = initial(
        inputs,
        arm=arm,
        mode=mode,
        hindsight_links=hindsight_links,
        history_lookback=history_lookback,
    )
    for cut in [*cuts, end]:
        result, state = resume_replay(
            state=state,
            inputs=inputs,
            cfg=CFG,
            mode=mode,
            arm=arm,
            end=cut,
            hindsight_links=hindsight_links,
        )
        if round_trip:
            state = ReplayState.from_json(json.loads(json.dumps(state.to_json())))
    return result, state


def full(
    inputs: ReplayInputs,
    *,
    arm: Arm = Arm.BASELINE,
    mode: ResearchMode = AUTH,
    end: datetime = END,
    hindsight_links: bool = False,
    history_lookback: timedelta | None = None,
) -> ReplayResult:
    return run_replay(
        inputs=inputs,
        cfg=CFG,
        mode=mode,
        arm=arm,
        start=START,
        end=end,
        hindsight_links=hindsight_links,
        history_lookback=history_lookback,
    )


TICKS = decision_times(START, END, CFG.decision_interval)
#: A stop inside the market-only arm's busiest stretch (positions open).
MID = H0 + timedelta(hours=47, minutes=40)


def _tick_after(t: datetime) -> datetime:
    """The first grid tick strictly after ``t``."""
    return next(x for x in TICKS if x > t)


def _state_at(inputs: ReplayInputs, cut: datetime, arm: Arm = Arm.BASELINE) -> ReplayState:
    _, state = resume_replay(
        state=initial(inputs, arm=arm), inputs=inputs, cfg=CFG, mode=AUTH, arm=arm, end=cut
    )
    return state


def _spread(cuts: list[datetime], n: int = 8) -> list[datetime]:
    """At most ``n`` of the candidate stops, evenly spread, in order."""
    cuts = sorted({c for c in cuts if START < c < END})
    if len(cuts) <= n:
        return cuts
    return [cuts[round(k * (len(cuts) - 1) / (n - 1))] for k in range(n)]


@pytest.fixture(scope="module")
def inputs() -> ReplayInputs:
    return world()


@pytest.fixture(scope="module")
def baseline(inputs: ReplayInputs) -> ReplayResult:
    return full(inputs)


@pytest.fixture(scope="module")
def market_only(inputs: ReplayInputs) -> ReplayResult:
    return full(inputs, arm=Arm.CONTROL_B_MARKET_ONLY)


@pytest.fixture(scope="module")
def mid_state(inputs: ReplayInputs) -> ReplayState:
    """The market-only arm's state at ``MID``: positions open, events, a
    decision log with open runs."""
    return _state_at(inputs, MID, Arm.CONTROL_B_MARKET_ONLY)


# --------------------------------------------------------------------------
# The world is as busy as it claims
# --------------------------------------------------------------------------


def test_the_world_exercises_what_the_equivalence_tests_rely_on(
    baseline: ReplayResult, market_only: ReplayResult, mid_state: ReplayState
) -> None:
    """An equivalence test over a quiet world proves nothing. Pin the variety."""
    types = {e.event_type for e in baseline.events}
    assert {
        EventType.NEW_ATTENTION_WAVE,
        EventType.SECOND_WAVE,
        EventType.THIRD_WAVE,
        EventType.MEME_REVIVAL,
        EventType.ATTENTION_DECAY,
        EventType.ATTENTION_INCREASE,
    } <= types
    reasons = {t.exit_reason for r in (baseline, market_only) for t in r.trades}
    assert {
        ExitReason.TAKE_PROFIT,
        ExitReason.STOP_LOSS,
        ExitReason.TRAILING_STOP,
        ExitReason.VOLUME_COLLAPSE,
        ExitReason.ATTENTION_COLLAPSE,
        ExitReason.MAX_HOLD,
        ExitReason.END_OF_DATA,
    } <= reasons, reasons
    assert baseline.metrics.trades >= 5
    assert market_only.rejection_counts.get("max_open", 0) > 0
    assert any(
        e["kind"] == "exit_check_unavailable"
        for t in market_only.trades
        for e in t.evidence_timeline
    )
    assert mid_state.open_positions and mid_state.open_runs and mid_state.closed
    assert any(
        p.exit_state.peak_price > p.exit_state.entry_price for p in mid_state.open_positions
    ) or any(t.exit_reason is ExitReason.TRAILING_STOP for t in market_only.trades)


# --------------------------------------------------------------------------
# Equivalence: stopping and continuing changes nothing
# --------------------------------------------------------------------------


@pytest.mark.parametrize("fraction", [0.5, 0.31])
def test_resume_from_a_midpoint_equals_the_full_replay(
    inputs: ReplayInputs, baseline: ReplayResult, fraction: float
) -> None:
    cut = START + (END - START) * fraction  # 0.31 is off the grid on purpose
    resumed, state = chained(inputs, [cut])
    assert_same(baseline, resumed)
    assert state.ticks == baseline.ticks and state.processed_until == TICKS[-1]


@pytest.mark.parametrize("busy", [True, False])
def test_a_resume_that_folds_no_new_tick_still_equals_the_full_replay(
    inputs: ReplayInputs, baseline: ReplayResult, busy: bool
) -> None:
    """Asked to continue to an ``end`` before the next tick, the resume adds
    nothing — and still closes the equity curve exactly as the full replay
    over that window does: both when the last tick moved the book (busy) and
    when it did not, so the closing point comes from the carried valuation."""
    if busy:
        arm, tick = Arm.CONTROL_B_MARKET_ONLY, MID
    else:
        arm = Arm.BASELINE
        moved = {s.at for s in baseline.snapshots}
        quiet = [t for t in TICKS[10:] if t not in moved]
        tick = quiet[len(quiet) // 2]
    cut = tick + timedelta(minutes=7)  # off the grid; the next tick is later
    end = cut + timedelta(minutes=3)
    state = _state_at(inputs, cut, arm)
    result, after = resume_replay(
        state=state, inputs=inputs, cfg=CFG, mode=AUTH, arm=arm, end=end
    )
    assert after == state
    assert_same(full(inputs, arm=arm, end=end), result)


def test_many_small_resumes_equal_the_full_replay(
    inputs: ReplayInputs, market_only: ReplayResult
) -> None:
    """Every 9th tick, through JSON each time: the market-only arm fills the
    book, hits the cap, and leaves positions open at the end."""
    resumed, _ = chained(inputs, TICKS[9::9], arm=Arm.CONTROL_B_MARKET_ONLY)
    assert_same(market_only, resumed)


def test_resume_at_every_tick_equals_the_full_replay(
    inputs: ReplayInputs, market_only: ReplayResult, mid_state: ReplayState
) -> None:
    """The densest stop pattern: one tick at a time across the busiest stretch,
    with positions open throughout it."""
    stretch = [t for t in TICKS if MID <= t < MID + timedelta(hours=6)]
    assert any(s.open_positions for s in market_only.snapshots if s.at in set(stretch))
    state = mid_state
    for cut in [*stretch[1:], END]:
        result, state = resume_replay(
            state=ReplayState.from_json(json.loads(json.dumps(state.to_json()))),
            inputs=inputs,
            cfg=CFG,
            mode=AUTH,
            arm=Arm.CONTROL_B_MARKET_ONLY,
            end=cut,
        )
    assert_same(market_only, result)


def _cuts_inside_open_positions(r: ReplayResult) -> list[datetime]:
    """A tick strictly inside each multi-tick position, entry and exit excluded."""
    cuts = []
    for t in r.trades:
        if t.exit_at is None:
            continue
        inside = [x for x in TICKS if t.entry_at < x < t.exit_at]
        if len(inside) >= 2:
            cuts.append(inside[len(inside) // 2])
    return cuts


def _cuts_before_exits(r: ReplayResult) -> list[datetime]:
    """The tick on which each exit fired: the resumed segment starts with it,
    so the exit is evaluated from the restored cursor, peak and notes."""
    return [_tick_after(t.exit_at - timedelta(microseconds=1)) for t in r.trades if t.exit_at]


def _cuts_inside_episodes(r: ReplayResult) -> list[datetime]:
    """Right after a wave starts (before its decay) and right after a
    re-armable event fired — the detectors' memory is all in prior events."""
    kinds = {
        EventType.NEW_ATTENTION_WAVE,
        EventType.SECOND_WAVE,
        EventType.THIRD_WAVE,
        EventType.MEME_REVIVAL,
        EventType.ATTENTION_INCREASE,
        EventType.ATTENTION_PRICE_DIVERGENCE,
    }
    return [_tick_after(e.detected_at) for e in r.events if e.event_type in kinds]


@pytest.mark.parametrize(
    "where", ["inside_open_position", "inside_attention_episode", "right_before_exit"]
)
@pytest.mark.parametrize("arm", [Arm.BASELINE, Arm.CONTROL_B_MARKET_ONLY])
def test_resume_at_the_hard_places_equals_the_full_replay(
    inputs: ReplayInputs,
    baseline: ReplayResult,
    market_only: ReplayResult,
    where: str,
    arm: Arm,
) -> None:
    reference = baseline if arm is Arm.BASELINE else market_only
    pick = {
        "inside_open_position": _cuts_inside_open_positions,
        "inside_attention_episode": _cuts_inside_episodes,
        "right_before_exit": _cuts_before_exits,
    }[where]
    cuts = _spread(pick(reference))
    assert len(cuts) >= 3, f"the world should offer several {where} stops"
    resumed, _ = chained(inputs, cuts, arm=arm)
    assert_same(reference, resumed)


def test_exploratory_with_backfill_and_hindsight_resumes_identically() -> None:
    """Backfilled rows enter on the EXPLORATORY timeline at their publication
    lag, links may be used with hindsight, and the result is labelled. None
    of that may depend on where the replay was stopped — including after the
    backfilled rows have aged out of the history window, when only the
    carried flag still remembers that backfill was ever used."""
    inp = world(3, backfill=True)
    end = H0 + timedelta(hours=56)
    lookback = timedelta(hours=10)
    kw: dict[str, Any] = {
        "mode": EXPL,
        "end": end,
        "hindsight_links": True,
        "history_lookback": lookback,
    }
    once = full(inp, **kw)
    assert once.contains_backfill and once.hindsight_links
    cuts = [START + timedelta(hours=h, minutes=15 * (h % 3)) for h in (2, 7, 11, 16, 24)]
    resumed, _ = chained(inp, cuts, **kw)
    assert_same(once, resumed)


def test_history_lookback_is_carried_and_honoured() -> None:
    """The forward replay bounds history (FORWARD_HISTORY_LOOKBACK); the bound
    lives in the state, so a resume cannot silently drop or change it."""
    inp = world(3)
    end = H0 + timedelta(hours=42)
    lookback = timedelta(hours=14)
    once = full(inp, end=end, history_lookback=lookback)
    resumed, state = chained(
        inp, [START + timedelta(hours=9)], end=end, history_lookback=lookback
    )
    assert state.history_lookback == lookback
    assert_same(once, resumed)


# --------------------------------------------------------------------------
# The state: JSON, immutability, determinism, refusal
# --------------------------------------------------------------------------


def test_state_round_trips_through_json_exactly(mid_state: ReplayState) -> None:
    """Decimals as strings, nothing lost: decode(encode(s)) == s, and the
    document is plain JSON (what the checkpoint table stores)."""
    doc = json.loads(json.dumps(mid_state.to_json()))
    again = ReplayState.from_json(doc)
    assert again == mid_state
    assert ReplayState.from_json(json.dumps(doc)) == mid_state
    assert again.to_json() == mid_state.to_json()
    for value in (doc["cash"], doc["realized_pnl"], doc["peak_equity"]):
        assert isinstance(value, str)
    assert isinstance(doc["open_positions"][0]["exit_state"]["peak_price"], str)


def test_resume_never_mutates_the_state_it_was_given(
    inputs: ReplayInputs, mid_state: ReplayState
) -> None:
    """A checkpoint is read, never written through: resuming twice from one
    state gives the same answer, and the state is unchanged after both."""
    before = json.dumps(mid_state.to_json(), sort_keys=True)
    kw: dict[str, Any] = {
        "inputs": inputs,
        "cfg": CFG,
        "mode": AUTH,
        "arm": Arm.CONTROL_B_MARKET_ONLY,
        "end": END,
    }
    a, sa = resume_replay(state=mid_state, **kw)
    b, sb = resume_replay(state=mid_state, **kw)
    assert json.dumps(mid_state.to_json(), sort_keys=True) == before
    assert_same(a, b)
    assert sa == sb


def test_checkpoint_at_returns_the_state_a_shorter_replay_ends_in(
    inputs: ReplayInputs, market_only: ReplayResult, mid_state: ReplayState
) -> None:
    """One pass can report to ``end`` and leave a checkpoint behind it; that
    checkpoint is exactly the state a replay ending there would have, and the
    state at ``end`` is the state a chained replay ends in."""
    result, cp = resume_replay(
        state=initial(inputs, arm=Arm.CONTROL_B_MARKET_ONLY),
        inputs=inputs,
        cfg=CFG,
        mode=AUTH,
        arm=Arm.CONTROL_B_MARKET_ONLY,
        end=END,
        checkpoint_at=MID,
    )
    assert_same(market_only, result)
    assert cp == mid_state
    assert cp.processed_until is not None and cp.processed_until < MID
    _, at_end = resume_replay(
        state=cp, inputs=inputs, cfg=CFG, mode=AUTH, arm=Arm.CONTROL_B_MARKET_ONLY, end=END
    )
    _, chained_end = chained(
        inputs, [START + timedelta(hours=13), MID], arm=Arm.CONTROL_B_MARKET_ONLY
    )
    assert at_end == chained_end


def test_a_state_only_continues_its_own_replay(
    inputs: ReplayInputs, mid_state: ReplayState
) -> None:
    """Mode, arm, links mode, configuration and meme set are part of the
    state's identity; a mismatch is refused, never silently resumed."""
    arm = Arm.CONTROL_B_MARKET_ONLY
    kw: dict[str, Any] = {"inputs": inputs, "cfg": CFG, "mode": AUTH, "arm": arm}
    with pytest.raises(ValueError, match="config"):
        resume_replay(
            state=mid_state,
            **{**kw, "cfg": replace(CFG, decision_interval=timedelta(minutes=5))},
            end=END,
        )
    with pytest.raises(ValueError, match="arm"):
        resume_replay(state=mid_state, **{**kw, "arm": Arm.CONTROL_D_COMBINED}, end=END)
    with pytest.raises(ValueError, match="mode"):
        resume_replay(state=mid_state, **{**kw, "mode": EXPL}, end=END)
    with pytest.raises(ValueError, match="hindsight"):
        resume_replay(
            state=replace(mid_state, mode=EXPL),
            **{**kw, "mode": EXPL},
            end=END,
            hindsight_links=True,
        )
    with pytest.raises(ValueError, match="meme_set"):
        resume_replay(
            state=mid_state,
            **{**kw, "inputs": replace(inputs, memes=inputs.memes[:-1])},
            end=END,
        )
    with pytest.raises(ValueError, match="past end"):
        resume_replay(state=mid_state, **kw, end=MID - timedelta(hours=1))
    doc = mid_state.to_json()
    with pytest.raises(ValueError, match="another engine"):
        ReplayState.from_json({**doc, "replay_version": "mll-replay-v0"})
    with pytest.raises(ValueError, match="format"):
        ReplayState.from_json({**doc, "format": 0})


def test_rows_known_after_the_state_are_picked_up_by_the_resume(
    inputs: ReplayInputs, market_only: ReplayResult
) -> None:
    """What resuming is for: rows that became known after the state's last
    tick are seen by the continuation exactly as by a full replay over the
    grown input set. (Rows known *before* it are the checkpoint's business.)"""
    cut = MID
    early = replace(
        inputs,
        observations=tuple(o for o in inputs.observations if o.retrieved_at <= cut),
        market=tuple(p for p in inputs.market if p.available_at <= cut),
        runs=tuple(r for r in inputs.runs if r.finished_at <= cut),
    )
    state = _state_at(early, cut, Arm.CONTROL_B_MARKET_ONLY)
    grown, _ = resume_replay(
        state=state,
        inputs=inputs,
        cfg=CFG,
        mode=AUTH,
        arm=Arm.CONTROL_B_MARKET_ONLY,
        end=END,
    )
    # The fingerprints differ (the inputs did); nothing the replay decided does.
    blank = {"input_fingerprint": ""}
    assert grown.to_dict() | blank == market_only.to_dict() | blank
