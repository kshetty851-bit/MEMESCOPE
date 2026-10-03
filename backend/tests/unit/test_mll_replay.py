"""Meme Lifecycle Lab — the point-in-time replay, end to end on the real engines.

The scenario: one meme with steady GDELT coverage (1 mention per 15 minutes)
that spikes over three hours to 10 per bucket, while its linked token's 1h
volume triples and its price is flat — then the price doubles 30 minutes after
the spike. The baseline strategy should enter during the spike, before the
pump, and the take-profit should close it at the target.

The properties these tests pin are the ones a backtest most often gets wrong:
no look-ahead, entry at a price that was visible, determinism regardless of
input order, links gated on ``linked_at``, and AUTHORITATIVE ignoring backfill.
"""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.lifecycle_lab.config import LabConfig
from app.lifecycle_lab.domain import (
    Arm,
    CollectionRun,
    DataClass,
    ExitReason,
    LinkMethod,
    MarketPoint,
    Meme,
    MemeTokenLink,
    Metric,
    Observation,
    ResearchMode,
    Source,
    SourceStatus,
    TokenInfo,
    ValueKind,
)
from app.lifecycle_lab.replay import ReplayInputs, ReplayResult, decision_times, run_replay

pytestmark = pytest.mark.unit

H0 = datetime(2026, 9, 1, tzinfo=UTC)
SPIKE_END = H0 + timedelta(days=2)  # S: the 10-per-bucket hour ends here
PUMP_AT = SPIKE_END + timedelta(minutes=30)
START = SPIKE_END - timedelta(hours=1)
END = SPIKE_END + timedelta(hours=3)
BUCKET = timedelta(minutes=15)
GDELT_LAG = timedelta(minutes=2)
MARKET_LAG = timedelta(seconds=30)
MINT = "MINTA"
CFG = LabConfig()
AUTH = ResearchMode.AUTHORITATIVE
EXPL = ResearchMode.EXPLORATORY


def _mentions(window_start: datetime) -> int:
    if SPIKE_END - timedelta(hours=1) <= window_start < SPIKE_END:
        return 10
    if SPIKE_END - timedelta(hours=2) <= window_start < SPIKE_END - timedelta(hours=1):
        return 2
    return 1


def scenario(
    *, linked_at: datetime = H0, data_class: DataClass = DataClass.FORWARD
) -> ReplayInputs:
    meme = Meme(id="m1", slug="m1", display_name="Meme One", tracking_started_at=H0)
    late = timedelta(days=30) if data_class is DataClass.BACKFILL else timedelta(0)
    obs: list[Observation] = []
    runs: list[CollectionRun] = []
    t = H0
    while t < END:
        end = t + BUCKET
        obs.append(
            Observation(
                source=Source.GDELT,
                metric=Metric.MENTIONS,
                value_kind=ValueKind.WINDOW_COUNT,
                data_class=data_class,
                source_timestamp=t,
                observed_at=end,
                retrieved_at=end + GDELT_LAG + late,
                raw_value=Decimal(_mentions(t)),
                meme_id="m1",
                window_start=t,
                window_end=end,
                query="meme one",
            )
        )
        runs.append(
            CollectionRun(
                id=f"run-{end.isoformat()}",
                source=Source.GDELT,
                status=SourceStatus.AVAILABLE,
                started_at=end + GDELT_LAG - timedelta(seconds=10),
                finished_at=end + GDELT_LAG + late,
                data_class=data_class,
            )
        )
        t = end
    market: list[MarketPoint] = []
    t = H0
    while t < END:
        market.append(
            MarketPoint(
                mint_address=MINT,
                observed_at=t,
                available_at=t + MARKET_LAG,
                data_class=data_class,
                price_usd=Decimal("2.5") if t >= PUMP_AT else Decimal("1"),
                market_cap=Decimal("100000"),
                liquidity_usd=None,
                volume_1h=(
                    Decimal(3000) if t >= SPIKE_END - timedelta(minutes=30) else Decimal(1000)
                ),
                source="token_market_snapshots" if data_class is DataClass.FORWARD else "gt",
            )
        )
        t += timedelta(minutes=5)
    return ReplayInputs(
        memes=(meme,),
        links=(
            MemeTokenLink(
                meme_id="m1",
                mint_address=MINT,
                method=LinkMethod.MANUAL,
                confidence=Decimal(1),
                linked_at=linked_at,
            ),
        ),
        tokens=(
            TokenInfo(
                mint_address=MINT,
                name="Meme One",
                symbol="ONE",
                created_at=H0 - timedelta(days=10),
                discovered_at=H0 - timedelta(days=10),
            ),
        ),
        observations=tuple(obs),
        market=tuple(market),
        runs=tuple(runs),
    )


def replay(inputs: ReplayInputs, **kw: Any) -> ReplayResult:
    args: dict[str, Any] = {
        "inputs": inputs,
        "cfg": CFG,
        "mode": AUTH,
        "arm": Arm.BASELINE,
        "start": START,
        "end": END,
    }
    args.update(kw)
    return run_replay(**args)


@pytest.fixture(scope="module")
def base() -> ReplayResult:
    return replay(scenario())


# --------------------------------------------------------------------------
# The scenario does what it says
# --------------------------------------------------------------------------


def test_scenario_enters_during_spike_and_takes_profit_at_target(base: ReplayResult) -> None:
    assert len(base.trades) == 1
    (trade,) = base.trades
    assert START < trade.entry_at < PUMP_AT
    assert trade.entry_price == Decimal(1)
    assert trade.status == "closed"
    assert trade.exit_reason is ExitReason.TAKE_PROFIT
    assert trade.exit_price == Decimal(2)  # target, not the 2.5 gap
    assert trade.exit_at is not None and trade.exit_at >= PUMP_AT + MARKET_LAG
    assert trade.cost_model == "flat"  # liquidity unknown
    assert trade.entry_reason == "conditions_met"
    assert base.metrics.trades == 1 and base.metrics.wins == 1
    assert not base.contains_backfill and not base.hindsight_links


def test_evidence_timeline_holds_only_what_preceded_entry(base: ReplayResult) -> None:
    (trade,) = base.trades
    timeline = list(trade.evidence_timeline)
    entry_idx = next(i for i, e in enumerate(timeline) if e["kind"] == "entry")
    for item in timeline[:entry_idx]:
        assert datetime.fromisoformat(item["at"]) <= trade.entry_at, item
    kinds = {e["kind"] for e in timeline}
    assert {"link_created", "entry_price_reading", "entry", "exit:take_profit"} <= kinds
    assert timeline[-1]["kind"] == "exit:take_profit"


def test_decision_log_records_why_not(base: ReplayResult) -> None:
    """Before the spike the strategy said no, with measured reasons; the log
    is run-length encoded so it stays compact over long replays."""
    first = base.decisions[0]
    assert first["status"] == "no_entry" and first["failed_conditions"]
    assert sum(d["ticks"] for d in base.decisions) == base.ticks
    assert (
        base.snapshots
        and base.snapshots[-1].at == decision_times(START, END, CFG.decision_interval)[-1]
    )


def test_end_of_data_is_marked_not_filled() -> None:
    """Cut the replay before the pump: the open position is labelled
    END_OF_DATA, never closed at an invented price, and excluded from stats."""
    r = replay(scenario(), end=PUMP_AT)
    (trade,) = r.trades
    assert trade.status == "open" and trade.exit_reason is ExitReason.END_OF_DATA
    assert trade.exit_price is None and trade.pnl_usd is None
    assert r.metrics.trades == 0 and r.metrics.open_at_end == 1
    assert r.open_at_end == (trade,)


# --------------------------------------------------------------------------
# No look-ahead
# --------------------------------------------------------------------------


def _mutate_after(inputs: ReplayInputs, cut: datetime) -> ReplayInputs:
    """Rewrite every fact that became known after ``cut``, and add misleading
    late facts — including late-arriving rows *about* the past."""
    obs = [
        replace(o, raw_value=o.raw_value * 7 + 3) if o.retrieved_at > cut else o
        for o in inputs.observations
    ]
    # A huge spike about the past, retrieved only after the cut.
    obs.append(
        Observation(
            source=Source.GDELT,
            metric=Metric.MENTIONS,
            value_kind=ValueKind.WINDOW_COUNT,
            data_class=DataClass.FORWARD,
            source_timestamp=START - BUCKET,
            observed_at=START,
            retrieved_at=cut + timedelta(minutes=1),
            raw_value=Decimal(10_000),
            meme_id="m1",
            window_start=START - BUCKET,
            window_end=START,
            query="late",
        )
    )
    market = [
        replace(p, price_usd=Decimal("0.01"), volume_1h=Decimal(1))
        if p.available_at > cut
        else p
        for p in inputs.market
    ]
    # A price observed before the cut that only became available after it.
    market.append(
        MarketPoint(
            mint_address=MINT,
            observed_at=START + timedelta(seconds=1),
            available_at=cut + timedelta(seconds=1),
            data_class=DataClass.FORWARD,
            price_usd=Decimal(1000),
            volume_1h=Decimal(10**9),
        )
    )
    runs = [
        replace(r, status=SourceStatus.ERROR, reason="mutated") if r.finished_at > cut else r
        for r in inputs.runs
    ]
    late_link = MemeTokenLink(
        meme_id="m1",
        mint_address="MINTB",
        method=LinkMethod.EXACT_SYMBOL,
        confidence=Decimal(1),
        linked_at=cut + timedelta(seconds=5),
    )
    return replace(
        inputs,
        observations=tuple(obs),
        market=tuple(market),
        runs=tuple(runs),
        links=(*inputs.links, late_link),
    )


def _decisions_up_to(r: ReplayResult, cut: datetime) -> list[tuple[Any, ...]]:
    keys = ("meme_id", "mint_address", "status", "reason_code", "rejection", "trade_key")
    return [
        (d["at"], *(d[k] for k in keys), tuple(d["failed_conditions"]))
        for d in r.decisions
        if datetime.fromisoformat(d["at"]) <= cut
    ]


def _entry_view(trade: Any) -> dict[str, Any]:
    d = trade.to_dict()
    d["evidence_timeline"] = [
        e for e in d["evidence_timeline"] if not e["kind"].startswith("exit")
    ]
    for k in (
        "exit_at",
        "exit_price",
        "exit_reason",
        "exit_fees_usd",
        "pnl_usd",
        "return_pct",
        "status",
        "cost_model",
    ):
        d.pop(k)
    return d


@pytest.mark.parametrize("cut_minutes", [-50, -20, 10, 40])
def test_no_look_ahead_mutating_the_future_changes_nothing_before_it(
    base: ReplayResult, cut_minutes: int
) -> None:
    """Rewrite everything that became known after T (and inject late rows about
    the past): every decision made at or before T, and every entry made at or
    before T, must be identical."""
    cut = SPIKE_END + timedelta(minutes=cut_minutes)
    mutated = replay(_mutate_after(scenario(), cut))
    assert _decisions_up_to(mutated, cut) == _decisions_up_to(base, cut)
    before = [_entry_view(t) for t in base.trades if t.entry_at <= cut]
    after = [_entry_view(t) for t in mutated.trades if t.entry_at <= cut]
    assert before == after
    assert [e for e in mutated.events if e.detected_at <= cut] == [
        e for e in base.events if e.detected_at <= cut
    ]


def test_entry_price_is_never_a_future_price() -> None:
    """The entry fills at the newest reading available at entry time. A point
    observed earlier but published later (price 1000) is never used."""
    cut = SPIKE_END - timedelta(minutes=40)
    r = replay(_mutate_after(scenario(), cut))
    for trade in r.trades:
        reading = next(
            e for e in trade.evidence_timeline if e["kind"] == "entry_price_reading"
        )
        assert datetime.fromisoformat(reading["detail"]["available_at"]) <= trade.entry_at
        assert datetime.fromisoformat(reading["at"]) <= trade.entry_at
        assert trade.entry_price != Decimal(1000)


def test_link_created_after_the_pump_yields_no_earlier_entry() -> None:
    """A link is a fact with a time. Linking the token an hour after it pumped
    must not produce a position before the link existed."""
    linked_at = PUMP_AT + timedelta(hours=1)
    r = replay(scenario(linked_at=linked_at))
    assert all(t.entry_at >= linked_at for t in r.trades)
    for d in r.decisions:
        if datetime.fromisoformat(d["at"]) < linked_at:
            assert d["mint_address"] is None and d["reason_code"] == "no_visible_link"


def test_hindsight_links_are_exploratory_only_and_stamped() -> None:
    linked_at = PUMP_AT + timedelta(hours=1)
    with pytest.raises(ValueError):
        replay(scenario(linked_at=linked_at), hindsight_links=True)
    r = replay(scenario(linked_at=linked_at), mode=EXPL, hindsight_links=True)
    assert r.hindsight_links
    assert r.trades, "hindsight should expose the pre-link entry"
    assert all(t.hindsight for t in r.trades)
    assert r.metrics.hindsight


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------


def test_same_inputs_twice_are_identical(base: ReplayResult) -> None:
    again = replay(scenario())
    assert again.to_dict() == base.to_dict()
    assert again.input_fingerprint == base.input_fingerprint


def test_shuffled_input_order_is_identical(base: ReplayResult) -> None:
    """Input order is not information. The replay sorts canonically, so a
    shuffled load produces the same result and the same fingerprint."""
    inputs = scenario()
    rng = random.Random(7)

    def shuffled(rows: tuple[Any, ...]) -> tuple[Any, ...]:
        out = list(rows)
        rng.shuffle(out)
        return tuple(out)

    mixed = ReplayInputs(
        memes=shuffled(inputs.memes),
        aliases=shuffled(inputs.aliases),
        links=shuffled(inputs.links),
        tokens=shuffled(inputs.tokens),
        observations=shuffled(inputs.observations),
        market=shuffled(inputs.market),
        runs=shuffled(inputs.runs),
    )
    r = replay(mixed)
    assert r.input_fingerprint == base.input_fingerprint
    assert r.to_dict() == base.to_dict()


def test_fingerprint_changes_with_inputs_config_mode_arm_and_window(
    base: ReplayResult,
) -> None:
    fp = base.input_fingerprint
    assert replay(scenario(linked_at=H0 + timedelta(seconds=1))).input_fingerprint != fp
    assert replay(scenario(), arm=Arm.CONTROL_D_COMBINED).input_fingerprint != fp
    assert replay(scenario(), mode=EXPL).input_fingerprint != fp
    assert replay(scenario(), end=END - timedelta(minutes=5)).input_fingerprint != fp
    other = replace(CFG, decision_interval=timedelta(minutes=10))
    assert replay(scenario(), cfg=other).input_fingerprint != fp


def test_decision_times_are_epoch_aligned() -> None:
    off = START + timedelta(minutes=2)
    ticks = decision_times(off, off + timedelta(minutes=20), timedelta(minutes=5))
    assert ticks[0] == START + timedelta(minutes=5)
    assert all((t - ticks[0]) % timedelta(minutes=5) == timedelta(0) for t in ticks)
    assert ticks[-1] < off + timedelta(minutes=20)


# --------------------------------------------------------------------------
# Modes
# --------------------------------------------------------------------------


def test_authoritative_ignores_backfill() -> None:
    """The same spike, but every row is BACKFILL (fetched 30 days later).
    AUTHORITATIVE sees none of it and does nothing; EXPLORATORY may use it and
    labels everything it produces."""
    backfilled = scenario(data_class=DataClass.BACKFILL)
    auth = replay(backfilled)
    assert auth.trades == ()
    assert not auth.contains_backfill
    assert all(d["status"] != "enter" for d in auth.decisions)
    expl = replay(backfilled, mode=EXPL)
    assert expl.contains_backfill
    assert expl.trades and all(t.contains_backfill for t in expl.trades)
    assert expl.metrics.contains_backfill


def test_authoritative_result_unchanged_by_adding_backfill(base: ReplayResult) -> None:
    fwd = scenario()
    extra = scenario(data_class=DataClass.BACKFILL)
    mixed = replace(
        fwd,
        observations=fwd.observations
        + tuple(replace(o, raw_value=o.raw_value * 50) for o in extra.observations),
        market=fwd.market + tuple(replace(p, price_usd=Decimal(9)) for p in extra.market),
    )
    r = replay(mixed)
    a, b = r.to_dict(), base.to_dict()
    a.pop("input_fingerprint")
    b.pop("input_fingerprint")
    assert a == b


# --------------------------------------------------------------------------
# Arms
# --------------------------------------------------------------------------


def test_control_a_never_trades_and_says_why() -> None:
    r = replay(scenario(), arm=Arm.CONTROL_A_EXISTING)
    assert r.trades == ()
    assert any(d["reason_code"] == "control_a_not_wired" for d in r.decisions)


def test_control_d_trades_like_baseline(base: ReplayResult) -> None:
    r = replay(scenario(), arm=Arm.CONTROL_D_COMBINED)
    assert [(t.entry_at, t.entry_price, t.exit_reason) for t in r.trades] == [
        (t.entry_at, t.entry_price, t.exit_reason) for t in base.trades
    ]


def test_result_to_dict_is_json_safe(base: ReplayResult) -> None:
    import json

    json.dumps(base.to_dict())
