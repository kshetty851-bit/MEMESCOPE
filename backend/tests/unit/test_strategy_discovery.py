"""The discovery engine: generation, splits, the seal, and the metrics. §33.

The tests that matter most here are not the ones checking arithmetic — they are
the ones checking that the *methodology* holds: that the holdout cannot be seen
during selection, that penalties never reward a losing strategy for trading
less, and that a schedule cached for speed produces exactly what an uncached
replay would.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.strategy_lab.discovery import (
    attribution,
    engine,
    scoring,
    service,
    space,
    splits,
)
from app.strategy_lab.opportunities import Opportunity
from app.strategy_lab.rules import EXECUTABLE_FLOOR_USD, Quote

T0 = datetime(2026, 8, 20, 0, 0, tzinfo=UTC)
DEEP = Decimal(500_000)


def quote(minutes: float, multiple: str, *, liquidity: Decimal | None = DEEP) -> Quote:
    return Quote(
        price_usd=Decimal(multiple),
        captured_at=T0 + timedelta(minutes=minutes),
        liquidity_usd=liquidity,
        executable=liquidity is not None and liquidity >= EXECUTABLE_FLOOR_USD,
    )


def opportunity(
    quotes,
    *,
    mint="MINT",
    at=T0,
    age_seconds=Decimal(6 * 3600),
    liq_to_mcap=Decimal("0.5"),
    liquidity=DEEP,
    buys=100,
    sells=50,
) -> Opportunity:
    return Opportunity(
        source_decision_id="00000000-0000-0000-0000-000000000000",
        mint_address=mint,
        eligible_at=at,
        entry_price=Decimal(1),
        liquidity_usd=liquidity,
        market_cap=Decimal(100_000),
        liq_to_mcap=liq_to_mcap,
        volume_24h=None,
        volume_1h=None,
        buys_24h=buys,
        sells_24h=sells,
        buy_sell_ratio_24h=None,
        pool_address="POOL",
        venue="pumpswap",
        trading_pair=None,
        discovery_age_seconds=age_seconds,
        first_discovered_at=None,
        radar_rank=None,
        radar_score=None,
        confidence_score=None,
        risk_score=None,
        risk_band=None,
        security_status=None,
        security_evaluated_at=None,
        observation_cadence_seconds=None,
        radar_input_snapshot_count=None,
        evidence_coverage_pct=None,
        quotes=tuple(quotes),
    )


def series(*multiples: str):
    out = [quote(i + 1, m) for i, m in enumerate(multiples)]
    out.append(quote(400, multiples[-1]))
    return out


# ── Generation, §10 ─────────────────────────────────────────────────────────


def test_generation_is_deterministic_and_bounded() -> None:
    first = space.generate()
    second = space.generate()
    assert [c.strategy_id for c in first] == [c.strategy_id for c in second]
    assert 500 <= len(first) <= 2000, len(first)


def test_the_space_is_a_full_factorial_so_attribution_is_balanced() -> None:
    generated = [c for c in space.generate() if not c.reference]
    expected = len(space.ENTRIES) * len(space.SIZES) * len(space.PROFITS) * len(space.EXITS)
    assert len(generated) == expected
    # Every level of every dimension appears the same number of times.
    for dimension in ("entry", "size", "profit", "exit"):
        counts: dict[str, int] = {}
        for candidate in generated:
            key = candidate.factors()[dimension]
            counts[key] = counts.get(key, 0) + 1
        assert len(set(counts.values())) == 1, (dimension, counts)


def test_definition_hashes_fingerprint_the_definition_not_the_name() -> None:
    generated = space.generate()
    assert len({c.strategy_id for c in generated}) == len(generated)
    # P3 and P6 carry identical rungs by the brief's own specification, so a
    # hash that fingerprints the *definition* must collide on them. One that
    # included the id could not, and would silently claim they were different.
    p3 = next(c for c in generated if c.profit.key == "P3")
    p6 = next(
        c
        for c in generated
        if c.profit.key == "P6"
        and c.entry.key == p3.entry.key
        and c.size_usd == p3.size_usd
        and c.exit.key == p3.exit.key
    )
    assert p3.definition_hash == p6.definition_hash
    assert p3.strategy_id != p6.strategy_id
    assert space.generate()[0].definition_hash == generated[0].definition_hash


def test_changing_a_threshold_changes_the_hash() -> None:
    base = space.generate()[0]
    altered = space.Candidate(
        strategy_id=base.strategy_id,
        version=base.version,
        entry=base.entry,
        size_usd=base.size_usd + 1,
        profit=base.profit,
        exit=base.exit,
        portfolio=base.portfolio,
    )
    assert altered.definition_hash != base.definition_hash


def test_every_candidate_explains_itself_in_english() -> None:
    for candidate in space.generate()[:60]:
        text = candidate.explain()
        assert "$" in text and "Exit:" in text
        assert "None" not in text and "{" not in text


def test_no_definition_holds_longer_than_the_universe_is_gated_for() -> None:
    """§1. A hold beyond `MAX_HOLD` would need a population the others lack."""
    for candidate in space.generate():
        assert candidate.exit.hold_for <= space.MAX_HOLD


# ── Entry admission, §4 ─────────────────────────────────────────────────────


def test_a_missing_feature_is_a_refusal_never_a_pass() -> None:
    entry = space.EntryConfig(key="t", label="t", min_liq_to_mcap=Decimal("0.2"))
    blind = opportunity(series("1"), liq_to_mcap=None)
    assert not engine.admits(entry, blind)


def test_the_age_gate_admits_only_old_enough_tokens() -> None:
    entry = next(e for e in space.ENTRIES if e.key == "E-age4")
    young = opportunity(series("1"), age_seconds=Decimal(3600))
    old = opportunity(series("1"), age_seconds=Decimal(5 * 3600))
    assert not engine.admits(entry, young)
    assert engine.admits(entry, old)


def test_the_sell_buy_band_rejects_inside_it_and_admits_outside() -> None:
    entry = next(e for e in space.ENTRIES if e.key == "E-sbband")
    inside = opportunity(series("1"), buys=100, sells=20)  # 0.20
    below = opportunity(series("1"), buys=100, sells=5)  # 0.05
    above = opportunity(series("1"), buys=100, sells=50)  # 0.50
    assert not engine.admits(entry, inside)
    assert engine.admits(entry, below)
    assert engine.admits(entry, above)


def test_sell_buy_is_computed_from_counts_not_inverted_from_a_ratio() -> None:
    entry = space.EntryConfig(key="t", label="t", min_sell_buy=Decimal("0.1"))
    no_buys = opportunity(series("1"), buys=0, sells=10)
    assert not engine.admits(entry, no_buys), "zero buys is unknown, not infinite"


# ── The schedule cache, §22 ─────────────────────────────────────────────────


def test_a_cached_schedule_matches_an_uncached_replay_exactly() -> None:
    """The optimisation must be exact, not merely close."""
    from app.strategy_lab.rules import resolve

    o = opportunity(series("1.10", "1.60", "1.90", "0.80"))
    cache = engine.ScheduleCache([o])
    candidate = next(
        c
        for c in space.generate()
        if c.profit.key == "P2" and c.exit.key == "X-hold6" and c.size_usd == Decimal(25)
    )
    cached = cache.get(0, "P2", "X-hold6", candidate.rules)

    direct = resolve(
        candidate.rules,
        entry_price=Decimal(1),
        opened_at=o.eligible_at,
        initial_quantity=Decimal(1),
        quotes=o.quotes,
    )
    assert [(f.at, f.price_usd, f.quantity) for f in direct.fills] == [
        (f.at, f.price_usd, f.fraction) for f in cached.fills
    ]


def test_the_cache_resolves_each_triple_once() -> None:
    o = opportunity(series("1.3", "1.6"))
    cache = engine.ScheduleCache([o])
    candidate = space.generate()[0]
    for _ in range(5):
        cache.get(0, candidate.profit.key, candidate.exit.key, candidate.rules)
    assert cache.resolutions == 1


def test_the_schedule_is_size_free_so_it_can_be_shared() -> None:
    """Fractions, not quantities — that is what makes reuse across sizes valid."""
    o = opportunity(series("1.3", "1.6", "1.9"))
    cache = engine.ScheduleCache([o])
    candidate = next(c for c in space.generate() if c.profit.key == "P2")
    schedule = cache.get(0, "P2", candidate.exit.key, candidate.rules)
    assert all(0 < f.fraction <= 1 for f in schedule.fills)
    assert sum(f.fraction for f in schedule.fills) == pytest.approx(
        Decimal(1), rel=Decimal("1e-9")
    )


# ── Capital, blocking, portfolio controls ───────────────────────────────────


def _candidate(**overrides) -> space.Candidate:
    base = next(
        c
        for c in space.generate()
        if c.entry.key == "E-none"
        and c.size_usd == Decimal(25)
        and c.profit.key == "P0"
        and c.exit.key == "X-hold6"
    )
    return space.Candidate(
        strategy_id=overrides.get("strategy_id", base.strategy_id),
        version=base.version,
        entry=overrides.get("entry", base.entry),
        size_usd=overrides.get("size_usd", base.size_usd),
        profit=overrides.get("profit", base.profit),
        exit=overrides.get("exit", base.exit),
        portfolio=overrides.get("portfolio", base.portfolio),
    )


def test_an_unfundable_entry_is_refused_and_counted() -> None:
    opportunities = [
        opportunity(series("1"), mint=f"M{i}", at=T0 + timedelta(seconds=i)) for i in range(60)
    ]
    cache = engine.ScheduleCache(opportunities)
    result = engine.evaluate(_candidate(), cache, range(60), block="T")
    assert result.n == 40
    assert result.refusals[engine.Refusal.NO_CASH] == 20


def test_the_exposure_cap_limits_concurrent_deployment() -> None:
    opportunities = [
        opportunity(series("1"), mint=f"M{i}", at=T0 + timedelta(seconds=i)) for i in range(40)
    ]
    cache = engine.ScheduleCache(opportunities)
    capped = _candidate(portfolio=next(p for p in space.PORTFOLIOS if p.key == "R-exp25"))
    result = engine.evaluate(capped, cache, range(40), block="T")
    assert result.n == 10, "25% of $1,000 funds ten $25 positions"
    assert result.refusals[engine.Refusal.EXPOSURE_CAP] == 30


def test_the_breaker_pauses_entries_after_repeated_catastrophes() -> None:
    rug = ["1", "0.0001"]
    opportunities = [
        opportunity(
            [
                quote(1, "1"),
                quote(200, "0.0001", liquidity=Decimal(0)),
                quote(400, "0.0001", liquidity=Decimal(0)),
            ],
            mint=f"M{i}",
            at=T0 + timedelta(hours=i),
        )
        for i in range(8)
    ]
    cache = engine.ScheduleCache(opportunities)
    with_breaker = _candidate(portfolio=next(p for p in space.PORTFOLIOS if p.key == "R-brkA"))
    without = _candidate()
    paused = engine.evaluate(with_breaker, cache, range(8), block="T")
    free = engine.evaluate(without, cache, range(8), block="T")
    assert paused.refusals.get(engine.Refusal.BREAKER, 0) > 0
    assert paused.n < free.n
    assert rug  # keeps the fixture name meaningful


def test_a_breaker_pause_never_stops_an_open_position_from_exiting() -> None:
    """§9. The same separation the live wallet's entry pause enforces."""
    source = inspect.getsource(engine._breaker_paused)
    assert "new entries only" in source
    # And behaviourally: everything a paused wallet did open still closed.
    opportunities = [
        opportunity(
            [
                quote(1, "1"),
                quote(200, "0.0001", liquidity=Decimal(0)),
                quote(400, "0.0001", liquidity=Decimal(0)),
            ],
            mint=f"M{i}",
            at=T0 + timedelta(hours=i),
        )
        for i in range(8)
    ]
    cache = engine.ScheduleCache(opportunities)
    paused = engine.evaluate(
        _candidate(portfolio=next(p for p in space.PORTFOLIOS if p.key == "R-brkA")),
        cache,
        range(8),
        block="T",
    )
    assert all(t.closed_at is not None for t in paused.trades)


def test_every_strategy_is_offered_the_identical_opportunity_set() -> None:
    """§1, across the whole search space."""
    opportunities = [
        opportunity(series("1.4", "0.9"), mint=f"M{i}", at=T0 + timedelta(minutes=i))
        for i in range(6)
    ]
    cache = engine.ScheduleCache(opportunities)
    for candidate in space.generate()[:40]:
        result = engine.evaluate(candidate, cache, range(6), block="T")
        assert result.offered == 6, candidate.strategy_id


# ── Splits, §11 / §12 / §24 ─────────────────────────────────────────────────


def _spread(count: int, *, hours_apart: float = 1.0):
    return [
        opportunity(
            series("1.2", "0.9"), mint=f"M{i}", at=T0 + timedelta(hours=i * hours_apart)
        )
        for i in range(count)
    ]


def test_the_split_is_chronological_and_never_overlaps() -> None:
    split = splits.chronological(_spread(40))
    assert split.discovery and split.validation and split.holdout
    latest_discovery = max(o.eligible_at for o in split.discovery)
    earliest_validation = min(o.eligible_at for o in split.validation)
    latest_validation = max(o.eligible_at for o in split.validation)
    earliest_holdout = min(o.eligible_at for o in split.holdout)
    assert latest_discovery < earliest_validation
    assert latest_validation < earliest_holdout


def test_no_bucket_is_split_across_two_blocks() -> None:
    split = splits.chronological(_spread(40, hours_apart=0.1))
    buckets = {
        "discovery": {
            o.eligible_at.replace(minute=0, second=0, microsecond=0) for o in split.discovery
        },
        "validation": {
            o.eligible_at.replace(minute=0, second=0, microsecond=0) for o in split.validation
        },
        "holdout": {
            o.eligible_at.replace(minute=0, second=0, microsecond=0) for o in split.holdout
        },
    }
    assert not buckets["discovery"] & buckets["validation"]
    assert not buckets["validation"] & buckets["holdout"]
    assert not buckets["discovery"] & buckets["holdout"]


def test_selection_cannot_reach_the_holdout() -> None:
    """§24's seal. Structural, so a future edit cannot quietly break it."""
    split = splits.chronological(_spread(40))
    visible = split.for_selection()
    assert len(visible) == 2
    holdout_mints = {o.mint_address for o in split.holdout}
    for block in visible:
        assert not {o.mint_address for o in block} & holdout_mints


def test_only_one_function_reads_the_holdout() -> None:
    """Counted over code, not prose — the docstrings name the seal on purpose."""
    import ast

    tree = ast.parse(inspect.getsource(service))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:] or [ast.Pass()]

    readers = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Attribute)
        and n.attr == "holdout"
        and isinstance(n.value, ast.Name)
        and n.value.id == "split"
    ]
    assert len(readers) == 1, ast.dump(tree)[:400]
    assert "split.holdout" in inspect.getsource(service._open_holdout)


def test_the_diagnosis_warns_when_one_day_dominates() -> None:
    crowded = [
        opportunity(series("1"), mint=f"M{i}", at=T0 + timedelta(minutes=i)) for i in range(50)
    ]
    diagnosis = splits.diagnose(crowded)
    assert diagnosis.granularity == splits.Granularity.HOUR
    assert any("NOT independent market regimes" in w for w in diagnosis.warnings)


def test_walk_forward_test_blocks_are_disjoint_and_strictly_later() -> None:
    folds = splits.walk_forward(_spread(20), train_buckets=5, step=1)
    assert folds
    seen: set[str] = set()
    for fold in folds:
        assert fold.train_to < fold.test_from
        mints = {o.mint_address for o in fold.test}
        assert not mints & seen, "walk-forward test blocks must not overlap"
        seen |= mints


def test_walk_forward_returns_nothing_when_history_is_too_short() -> None:
    assert splits.walk_forward(_spread(3), train_buckets=5) == []


# ── Scoring, §13 / §17 / §18 ────────────────────────────────────────────────


def _evaluation(
    pnls: list[str], *, offered: int | None = None, capital="1000"
) -> engine.Evaluation:
    trades = []
    for index, pnl in enumerate(pnls):
        trades.append(
            engine.Trade(
                mint_address=f"M{index}",
                opened_at=T0 + timedelta(days=index),
                closed_at=T0 + timedelta(days=index, minutes=30),
                size_usd=Decimal(25),
                entry_cost=Decimal(0),
                net_proceeds=Decimal(25) + Decimal(pnl),
                gross_proceeds=Decimal(25) + Decimal(pnl),
                exit_costs=Decimal(0),
                banked_before_final=Decimal(0),
                final_reason="expiry",
                unsettled=False,
                observed_peak_multiple=Decimal(1),
                executable_peak_multiple=Decimal(1),
                fills=1,
            )
        )
    total = sum((t.net_pnl for t in trades), Decimal(0))
    return engine.Evaluation(
        strategy_id="T",
        block="T",
        starting_capital=Decimal(capital),
        final_cash=Decimal(capital) + total,
        offered=offered if offered is not None else len(pnls),
        trades=trades,
        refusals={},
        peak_concurrent=1,
        equity_curve=[
            (T0, Decimal(capital)),
            (T0 + timedelta(hours=1), Decimal(capital) + total),
        ],
    )


def test_a_penalty_always_moves_a_score_down_whatever_its_sign() -> None:
    """The bug this engine shipped with, and the reason `penalise` exists.

    Multiplying by a factor below 1 shrinks a *loss* toward zero, which raises
    its rank. On a dataset where everything loses, that inverts the whole board
    and hands first place to whichever rule traded least.
    """
    factor = Decimal("0.5")
    assert scoring.penalise(Decimal(100), factor) < Decimal(100)
    assert scoring.penalise(Decimal(-100), factor) < Decimal(-100)


def test_refusing_almost_everything_is_penalised_not_rewarded() -> None:
    """§18, stated as the property it actually is.

    The penalty cannot claim that trading less is *worse for the wallet* — with
    identical per-trade economics, fewer losing trades is genuinely a smaller
    loss. What it must do is push a low-capture record DOWN relative to where it
    would otherwise sit, in both directions of sign, and flag it.
    """
    thin = _evaluation(["-1"] * 8, offered=100)  # 8% capture
    wide = _evaluation(["-1"] * 8, offered=20)  # 40% capture, same trades

    thin_score, thin_parts = scoring.score(thin)
    wide_score, wide_parts = scoring.score(wide)

    assert thin_parts["capture"] < wide_parts["capture"]
    assert thin_score < wide_score, "same trades, less capture, must rank lower"
    assert scoring.Flag.LOW_CAPTURE in scoring.flags_for(thin)
    assert scoring.Flag.LOW_CAPTURE not in scoring.flags_for(wide)

    # And the same holds for a winning record.
    thin_win = _evaluation(["1"] * 8, offered=100)
    wide_win = _evaluation(["1"] * 8, offered=20)
    assert scoring.score(thin_win)[0] < scoring.score(wide_win)[0]


def test_a_bigger_drawdown_ranks_lower_for_a_loser_too() -> None:
    mild = _evaluation(["-1"] * 60, offered=100)
    severe = _evaluation(["-1"] * 59 + ["-400"], offered=100)
    assert scoring.score(severe)[0] < scoring.score(mild)[0]


def test_the_evidence_floor_rejects_a_record_too_thin_to_measure() -> None:
    verdict = scoring.judge(_evaluation(["5"] * 4, offered=100))
    assert not verdict.survives
    assert any("evidence floor" in r for r in verdict.reasons)
    assert scoring.Flag.NO_EVIDENCE in verdict.flags


def test_an_undefined_profit_factor_is_not_treated_as_infinite() -> None:
    """Four winning trades and no loser is not a profit factor of infinity."""
    verdict = scoring.judge(_evaluation(["5"] * 4, offered=100))
    assert _evaluation(["5"] * 4).profit_factor is None
    assert any("undefined" in r for r in verdict.reasons)


def test_the_survival_filters_reject_what_section_13_lists() -> None:
    losing = scoring.judge(_evaluation(["-1"] * 60, offered=100))
    assert not losing.survives
    assert any("expectancy" in r for r in losing.reasons)
    assert any("profit factor" in r for r in losing.reasons)


def test_a_strategy_carried_by_one_trade_is_flagged_and_rejected() -> None:
    carried = _evaluation(["900"] + ["-10"] * 59, offered=100)
    verdict = scoring.judge(carried)
    assert carried.outlier_dependent
    assert scoring.Flag.OUTLIER_DEPENDENT in verdict.flags
    assert not verdict.survives


def test_outlier_removal_reports_each_requested_cut() -> None:
    evaluation = _evaluation(["100", "50", "25", "10", "5", "-10"], offered=10)
    assert evaluation.without(best=1) == Decimal(80)
    assert evaluation.without(best=3) == Decimal(5)
    assert evaluation.without(best=5) == Decimal(-10)
    assert evaluation.without(worst=1) == Decimal(190)
    assert evaluation.without(worst=3) == Decimal(175)
    assert evaluation.top_share_pct(1) == pytest.approx(
        Decimal("52.6315"), rel=Decimal("1e-3")
    )


def test_daily_consistency_is_measured_across_days() -> None:
    evaluation = _evaluation(["10", "-5", "20"], offered=10)
    assert len(evaluation.daily()) == 3
    assert evaluation.profitable_day_pct == pytest.approx(
        Decimal("66.66"), rel=Decimal("1e-2")
    )
    assert evaluation.worst_day == Decimal(-5)
    assert evaluation.best_day == Decimal(20)


def test_champion_standards_are_all_required() -> None:
    weak = _evaluation(["1"] * 12, offered=100)
    assert not scoring.is_champion(weak)
    unmet = [s.label for s in scoring.champion_standards(weak) if not s.met]
    assert "N >= 50" in unmet
    assert "capture >= 20%" in unmet


# ── Moonshots and rugs, §19 / §20 ───────────────────────────────────────────


def test_moonshot_retention_uses_the_executable_peak() -> None:
    o = opportunity([quote(1, "1"), quote(2, "50", liquidity=Decimal(0)), quote(400, "1")])
    cache = engine.ScheduleCache([o])
    result = engine.evaluate(_candidate(), cache, [0], block="T")
    assert result.moonshot(Decimal(10))["entered"] == 0


def test_rug_economics_credit_what_the_ladder_banked() -> None:
    o = opportunity(
        [
            quote(1, "1.30"),
            quote(2, "1.60"),
            quote(3, "1.90"),
            quote(200, "0.0001", liquidity=Decimal(0)),
            quote(400, "0.0001", liquidity=Decimal(0)),
        ]
    )
    cache = engine.ScheduleCache([o])
    laddered = _candidate(profit=next(p for p in space.PROFITS if p.key == "P2"))
    plain = _candidate(profit=next(p for p in space.PROFITS if p.key == "P0"))
    with_ladder = engine.evaluate(laddered, cache, [0], block="T")
    without = engine.evaluate(plain, cache, [0], block="T")
    assert with_ladder.catastrophes and without.catastrophes
    assert with_ladder.rug_capital_recovered > 0
    assert without.rug_capital_recovered == 0
    assert with_ladder.rug_loss_usd < without.rug_loss_usd


# ── Comparison and attribution, §21 / §30 ───────────────────────────────────


def test_shared_entry_comparison_separates_selection_from_management() -> None:
    a = _evaluation(["10", "10"], offered=10)
    b = _evaluation(["5", "5"], offered=10)
    comparison = attribution.compare(a, b)
    assert comparison.shared_mints == 2
    assert comparison.management_edge == Decimal(10)
    assert comparison.selection_edge == Decimal(0)


def test_attribution_covers_every_dimension_and_level() -> None:
    opportunities = _spread(12)
    cache = engine.ScheduleCache(opportunities)
    generated = space.generate()[:80]
    pairs = [
        (c, engine.evaluate(c, cache, range(len(opportunities)), block="T")) for c in generated
    ]
    attributed = attribution.attribute(pairs, survivors=set())
    assert {"entry", "size", "profit", "exit", "portfolio"} <= set(attributed)
    for levels in attributed.values():
        assert all(level.n_strategies > 0 for level in levels)
