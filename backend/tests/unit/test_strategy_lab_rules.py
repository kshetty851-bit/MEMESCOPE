"""The exit resolver and the replay engine, on hand-built series.

Every test here builds its own observations, so a failure names a rule rather
than a dataset. The scenarios are the ones §25 asks for, and each one exists
because getting it wrong produces a *plausible* number rather than a crash —
which is the only kind of bug that matters in research code.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.strategy_lab import execution, metrics, replay, rules, strategies
from app.strategy_lab.opportunities import Opportunity

T0 = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
DEEP = Decimal(500_000)


def quote(minutes: float, multiple: str, *, liquidity: Decimal | None = DEEP) -> rules.Quote:
    """One observation at `multiple` of a 1.0 entry price."""
    return rules.Quote(
        price_usd=Decimal(multiple),
        captured_at=T0 + timedelta(minutes=minutes),
        liquidity_usd=liquidity,
        executable=liquidity is not None and liquidity >= rules.EXECUTABLE_FLOOR_USD,
    )


def resolve(definition, quotes, **kwargs):
    return rules.resolve(
        definition.rules,
        entry_price=Decimal(1),
        opened_at=T0,
        initial_quantity=Decimal(100),
        quotes=quotes,
        **kwargs,
    )


def opportunity(
    quotes, *, mint="MINT", at=T0, age_seconds=Decimal(60), price="1"
) -> Opportunity:
    return Opportunity(
        source_decision_id="00000000-0000-0000-0000-000000000000",
        mint_address=mint,
        eligible_at=at,
        entry_price=Decimal(price),
        liquidity_usd=DEEP,
        market_cap=None,
        liq_to_mcap=None,
        volume_24h=None,
        volume_1h=None,
        buys_24h=None,
        sells_24h=None,
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


# ── Partial exits ───────────────────────────────────────────────────────────


def test_ladder_takes_each_rung_once_and_leaves_the_runner() -> None:
    outcome = resolve(
        strategies.S1,
        [quote(1, "1.30"), quote(2, "1.55"), quote(3, "1.80"), quote(400, "1.90")],
    )
    targets = [f for f in outcome.fills if f.reason is rules.FillReason.TARGET]
    assert len(targets) == 3
    assert [f.rung_indexes for f in targets] == [(0,), (1,), (2,)]
    # 25% of the ORIGINAL quantity per rung, never 25% of the remainder.
    assert all(f.quantity == Decimal(25) for f in targets)
    expiry = outcome.fills[-1]
    assert expiry.reason is rules.FillReason.EXPIRY
    assert expiry.quantity == Decimal(25)


def test_a_rung_never_fires_twice_however_often_its_level_is_revisited() -> None:
    outcome = resolve(
        strategies.S1,
        [
            quote(1, "1.30"),
            quote(2, "1.10"),
            quote(3, "1.30"),
            quote(4, "1.30"),
            quote(400, "1"),
        ],
    )
    fired = [f for f in outcome.fills if 0 in f.rung_indexes]
    assert len(fired) == 1


def test_cash_comes_back_after_each_partial_and_the_arithmetic_closes() -> None:
    result = replay.run(
        strategies.S1,
        [opportunity([quote(1, "1.30"), quote(2, "1.60"), quote(3, "1.80"), quote(400, "2")])],
    )
    position = result.positions[0]
    assert len(position.fills) == 4
    # Final cash is the stake back plus this position's net P&L, exactly.
    assert result.final_cash == pytest.approx(
        replay.STARTING_CAPITAL + position.net_pnl, rel=Decimal("1e-9")
    )


# ── Multi-target crossing, §5 ───────────────────────────────────────────────


def test_a_gap_through_three_rungs_fills_once_at_the_observed_price() -> None:
    """§5's rule: 1.10x → 1.80x never printed 1.25, 1.50 or 1.75."""
    outcome = resolve(strategies.S1, [quote(1, "1.10"), quote(2, "1.80"), quote(400, "1")])
    targets = [f for f in outcome.fills if f.reason is rules.FillReason.TARGET]
    assert len(targets) == 1
    assert targets[0].rung_indexes == (0, 1, 2)
    assert targets[0].price_usd == Decimal("1.80")
    assert targets[0].quantity == Decimal(75)
    assert outcome.batch_rung_fills == 1


def test_a_batch_fill_is_charged_as_one_larger_order() -> None:
    """Impact is quadratic, so three separate sales are cheaper than one big one.

    Charging the batch as three would understate the cost of exactly the gap
    the polling model claims to capture.
    """
    thin = Decimal(4_000)
    one_big, _ = execution.sell(Decimal(75), Decimal("1.80"), thin)
    three_small = sum(execution.sell(Decimal(25), Decimal("1.80"), thin)[0] for _ in range(3))
    assert one_big < three_small


# ── Expiry ──────────────────────────────────────────────────────────────────


def test_expiry_closes_everything_at_the_observed_price() -> None:
    outcome = resolve(strategies.S5, [quote(10, "3"), quote(361, "0.40")])
    assert len(outcome.fills) == 1
    assert outcome.fills[0].reason is rules.FillReason.EXPIRY
    assert outcome.fills[0].price_usd == Decimal("0.40")
    assert outcome.closed


def test_an_ambiguous_bar_at_expiry_books_the_clock_not_the_win() -> None:
    """A reading that is both past six hours and up 30% resolves adverse-first."""
    outcome = resolve(strategies.S1, [quote(361, "1.30")])
    assert [f.reason for f in outcome.fills] == [rules.FillReason.EXPIRY]


# ── Dead pools and rugs, §6 ─────────────────────────────────────────────────


def test_a_rung_cannot_fill_against_a_pool_nobody_could_sell_into() -> None:
    outcome = resolve(
        strategies.S1,
        [quote(1, "2.00", liquidity=Decimal(100)), quote(400, "1", liquidity=Decimal(100))],
    )
    assert not [f for f in outcome.fills if f.reason is rules.FillReason.TARGET]


def test_a_dead_pool_settlement_cannot_claim_a_price_printed_after_depth_vanished() -> None:
    """The single most important test in this file.

    A drained pool keeps printing a number. In the live dataset one printed
    1286x *after* liquidity reached zero, and booking it made a total loss into
    the largest profit in the result set — 88% of all P&L from one rugged token.
    """
    outcome = resolve(
        strategies.S5,
        [
            quote(1, "0.60"),
            quote(200, "500", liquidity=Decimal(0)),
            quote(400, "500", liquidity=Decimal(0)),
        ],
    )
    settlement = outcome.fills[-1]
    assert settlement.reason is rules.FillReason.DEAD_POOL
    assert settlement.price_usd == Decimal("0.60"), "capped at the last executable print"


def test_an_empty_pool_returns_nothing_at_all() -> None:
    proceeds, _ = execution.sell(Decimal(1_000), Decimal(50), Decimal(0))
    assert proceeds == Decimal(0)


def test_a_rug_after_partial_profits_keeps_what_the_ladder_banked() -> None:
    result = replay.run(
        strategies.S1,
        [
            opportunity(
                [
                    quote(1, "1.30"),
                    quote(2, "1.60"),
                    quote(3, "1.80"),
                    quote(200, "0.001", liquidity=Decimal(0)),
                    quote(400, "0.001", liquidity=Decimal(0)),
                ]
            )
        ],
    )
    position = result.positions[0]
    assert position.is_catastrophic
    assert position.banked_before_final > 0, "three rungs paid before the collapse"
    # The runner is worthless, but the banked 75% is real and still in cash.
    assert result.final_cash > replay.STARTING_CAPITAL - position.size_usd


def test_a_rug_before_any_target_loses_the_whole_stake() -> None:
    result = replay.run(
        strategies.S1,
        [
            opportunity(
                [
                    quote(1, "0.90"),
                    quote(200, "0.0001", liquidity=Decimal(0)),
                    quote(400, "0.0001", liquidity=Decimal(0)),
                ]
            )
        ],
    )
    position = result.positions[0]
    assert position.banked_before_final == 0
    assert position.net_pnl == -position.size_usd


def test_a_series_that_ends_while_the_pool_looks_healthy_is_unknown_not_a_rug() -> None:
    result = replay.run(strategies.S5, [opportunity([quote(1, "1.20"), quote(10, "1.10")])])
    position = result.positions[0]
    assert position.unsettled
    assert position.fills[-1][0].reason is rules.FillReason.DATA_UNAVAILABLE
    assert not position.is_catastrophic, "a feed gap is not a rug"


# ── Trailing, activation, and time decay ────────────────────────────────────


def test_the_trail_cannot_fire_on_the_reading_that_armed_it() -> None:
    outcome = resolve(strategies.S8, [quote(1, "1.50"), quote(400, "1.50")])
    assert not [f for f in outcome.fills if f.reason is rules.FillReason.TRAILING_STOP]


def test_the_trail_does_nothing_below_its_activation_however_far_price_falls() -> None:
    outcome = resolve(strategies.S8, [quote(1, "0.10"), quote(2, "0.05"), quote(400, "0.05")])
    assert [f.reason for f in outcome.fills] == [rules.FillReason.EXPIRY]


def test_the_trail_fires_at_the_observed_price_after_a_giveback() -> None:
    outcome = resolve(
        strategies.S8, [quote(1, "1.60"), quote(2, "4.00"), quote(3, "2.50"), quote(400, "1")]
    )
    stop = outcome.fills[0]
    assert stop.reason is rules.FillReason.TRAILING_STOP
    assert stop.price_usd == Decimal("2.50"), "the observation, not the trigger"
    assert stop.trigger_price == Decimal("2.60")


def test_s7_sells_its_rung_and_arms_on_the_same_reading() -> None:
    outcome = resolve(
        strategies.S7, [quote(1, "1.50"), quote(2, "3.00"), quote(3, "2.00"), quote(400, "1")]
    )
    reasons = [f.reason for f in outcome.fills]
    assert reasons[0] is rules.FillReason.TARGET
    assert rules.FillReason.TRAILING_STOP in reasons
    assert outcome.fills[0].quantity == Decimal(25)


def test_time_decay_frees_a_stagnant_position_and_leaves_a_live_one_alone() -> None:
    dead = resolve(strategies.S6, [quote(1, "1.02"), quote(61, "0.98"), quote(400, "0.5")])
    assert dead.fills[0].reason is rules.FillReason.TIME_DECAY

    alive = resolve(strategies.S6, [quote(1, "1.40"), quote(61, "0.98"), quote(400, "1.1")])
    assert alive.fills[0].reason is rules.FillReason.EXPIRY, "it exceeded 1.10x, so it stays"


def test_decay_ignores_a_peak_that_was_never_executable() -> None:
    outcome = resolve(
        strategies.S6,
        [quote(1, "1.50", liquidity=Decimal(50)), quote(61, "0.98"), quote(400, "0.5")],
    )
    assert outcome.fills[0].reason is rules.FillReason.TIME_DECAY


# ── Capital, blocking, concurrency ──────────────────────────────────────────


def test_each_strategy_starts_with_its_own_thousand_dollars() -> None:
    opportunities = [
        opportunity([quote(1, "1.1"), quote(400, "1")], mint=f"M{i}") for i in range(3)
    ]
    results = [replay.run(d, opportunities) for d in strategies.ALL]
    assert {r.starting_capital for r in results} == {Decimal(1000)}


def test_every_strategy_is_offered_the_identical_opportunity_set() -> None:
    """§1's requirement, asserted rather than assumed."""
    opportunities = [
        opportunity(
            [quote(1, "1.6"), quote(400, "1")], mint=f"M{i}", at=T0 + timedelta(minutes=i)
        )
        for i in range(5)
    ]
    for definition in strategies.ALL:
        result = replay.run(definition, opportunities)
        seen = {p.mint_address for p in result.positions} | {
            m.mint_address for m in result.missed
        }
        assert seen == {f"M{i}" for i in range(5)}, definition.strategy_id


def test_an_unfundable_entry_is_refused_and_recorded_never_skipped() -> None:
    many = [
        opportunity(
            [quote(1, "1"), quote(400, "1")], mint=f"M{i}", at=T0 + timedelta(seconds=i)
        )
        for i in range(60)
    ]
    result = replay.run(strategies.S5, many)
    assert result.taken == 40, "$1,000 funds exactly forty $25 entries"
    assert result.blocked_for_cash == 20
    assert all(m.reason == replay.Refusal.NO_CASH for m in result.missed)


def test_the_age_gate_refuses_before_cash_is_even_considered() -> None:
    young = opportunity([quote(1, "1"), quote(400, "1")], age_seconds=Decimal(60))
    result = replay.run(strategies.S9, [young])
    assert result.missed[0].reason == replay.Refusal.AGE_GATE

    old = opportunity(
        [quote(1, "1"), quote(400, "1")], age_seconds=Decimal(5 * 3600), mint="OLD"
    )
    assert replay.run(strategies.S9, [old]).taken == 1


def test_concurrency_is_counted_and_peaks_are_reported() -> None:
    overlapping = [
        opportunity(
            [quote(1, "1"), quote(400, "1")], mint=f"M{i}", at=T0 + timedelta(seconds=i)
        )
        for i in range(5)
    ]
    result = replay.run(strategies.S5, overlapping)
    assert result.peak_concurrent == 4
    assert result.avg_concurrency > 0


# ── Determinism, look-ahead, and versioning ─────────────────────────────────


def test_the_replay_is_deterministic() -> None:
    opportunities = [
        opportunity([quote(1, "1.3"), quote(2, "0.7"), quote(400, "1.1")], mint=f"M{i}")
        for i in range(10)
    ]
    a = replay.run(strategies.S1, opportunities)
    b = replay.run(strategies.S1, opportunities)
    assert a.final_cash == b.final_cash
    assert [p.net_pnl for p in a.positions] == [p.net_pnl for p in b.positions]


def test_a_later_observation_cannot_change_an_earlier_decision() -> None:
    """No look-ahead: truncating the future leaves the past's fills identical."""
    full = [quote(1, "1.30"), quote(2, "1.10"), quote(3, "9.00"), quote(400, "1")]
    early = resolve(strategies.S1, full[:2])
    late = resolve(strategies.S1, full)
    assert late.fills[0] == early.fills[0]


def test_changing_a_threshold_changes_the_definition_hash() -> None:
    original = strategies.S1.definition_hash
    altered = strategies.StrategyDefinition(
        strategy_id="S1",
        version="1.0.0",
        name=strategies.S1.name,
        purpose=strategies.S1.purpose,
        entry_size_usd=strategies.S1.entry_size_usd,
        rules=rules.StrategyRules(
            rungs=(
                rules.Rung(multiple=Decimal("1.30"), fraction=Decimal("0.25")),
                rules.Rung(multiple=Decimal("1.60"), fraction=Decimal("0.25")),
                rules.Rung(multiple=Decimal("2.00"), fraction=Decimal("0.25")),
            ),
            hold_for=timedelta(hours=6),
        ),
    )
    assert altered.definition_hash != original


def test_renaming_a_strategy_does_not_change_its_hash() -> None:
    renamed = strategies.StrategyDefinition(
        strategy_id="S1",
        version="1.0.0",
        name="Something else entirely",
        purpose="reworded",
        entry_size_usd=strategies.S1.entry_size_usd,
        rules=strategies.S1.rules,
    )
    assert renamed.definition_hash == strategies.S1.definition_hash


def test_every_registered_strategy_key_is_unique() -> None:
    keys = [d.key for d in strategies.ALL]
    assert len(set(keys)) == len(keys)


def test_s3_and_s10_resolve_identically_as_documented() -> None:
    series = [quote(1, "1.3"), quote(2, "1.6"), quote(400, "2.5")]
    assert resolve(strategies.S3, series).fills == resolve(strategies.S10, series).fills


# ── Resume, for forward research ────────────────────────────────────────────


def test_resuming_mid_series_produces_the_same_fills_as_one_pass() -> None:
    """§25's restart idempotency, at the level that actually decides it."""
    series = [quote(1, "1.30"), quote(2, "1.60"), quote(3, "1.80"), quote(400, "2")]
    whole = resolve(strategies.S1, series)

    first = resolve(strategies.S1, series[:2])
    second = rules.resolve(
        strategies.S1.rules,
        entry_price=Decimal(1),
        opened_at=T0,
        initial_quantity=Decimal(100),
        quotes=series[2:],
        resume=rules.Resume(
            remaining_quantity=first.remaining_quantity,
            filled_rungs=first.filled_rungs,
            observed_peak_multiple=first.observed_peak_multiple,
            executable_peak_multiple=first.executable_peak_multiple,
            batch_rung_fills=first.batch_rung_fills,
            last_executable_price=first.last_executable_price,
        ),
    )
    assert list(first.fills) + list(second.fills) == list(whole.fills)


def test_a_resume_never_refires_a_rung_it_was_told_about() -> None:
    outcome = rules.resolve(
        strategies.S1.rules,
        entry_price=Decimal(1),
        opened_at=T0,
        initial_quantity=Decimal(100),
        quotes=[quote(5, "1.30"), quote(400, "1")],
        resume=rules.Resume(remaining_quantity=Decimal(75), filled_rungs=frozenset({0})),
    )
    assert not [f for f in outcome.fills if 0 in f.rung_indexes]


# ── Execution costs ─────────────────────────────────────────────────────────


def test_costs_are_charged_on_both_sides_and_gross_is_never_shown_as_net() -> None:
    result = replay.run(strategies.S5, [opportunity([quote(1, "1"), quote(400, "2")])])
    position = result.positions[0]
    assert position.entry_cost > 0
    assert position.exit_costs > 0
    assert position.net_pnl < position.gross_pnl


def test_a_deeper_pool_costs_less_than_a_thin_one_for_the_same_order() -> None:
    deep, _ = execution.sell(Decimal(100), Decimal(10), Decimal(1_000_000))
    thin, _ = execution.sell(Decimal(100), Decimal(10), Decimal(5_000))
    assert deep > thin


def test_no_order_can_ever_return_negative_proceeds() -> None:
    for liquidity in (Decimal(0), Decimal(1), Decimal(500), Decimal(10_000)):
        proceeds, _ = execution.sell(Decimal(10_000), Decimal(99), liquidity)
        assert proceeds >= 0, liquidity


# ── Metrics ─────────────────────────────────────────────────────────────────


def _result_with(pnls: list[str]) -> replay.Result:
    positions = []
    for index, pnl in enumerate(pnls):
        position = replay.Position(
            mint_address=f"M{index}",
            source_decision_id="x",
            opened_at=T0 + timedelta(minutes=index),
            entry_price=Decimal(1),
            size_usd=Decimal(25),
            initial_quantity=Decimal(25),
            entry_cost=Decimal(0),
            entry_liquidity_usd=DEEP,
            venue="pumpswap",
            pool_address="POOL",
            discovery_age_seconds=None,
        )
        position.fills.append(
            (
                rules.Fill(
                    at=T0 + timedelta(hours=6),
                    price_usd=Decimal(1),
                    quantity=Decimal(25),
                    reason=rules.FillReason.EXPIRY,
                    liquidity_usd=DEEP,
                ),
                Decimal(25) + Decimal(pnl),
                Decimal(0),
            )
        )
        positions.append(position)
    return replay.Result(
        strategy_id="T",
        version="1.0.0",
        definition_hash="h",
        starting_capital=Decimal(1000),
        entry_size_usd=Decimal(25),
        positions=positions,
        missed=[],
        offered=len(positions),
        final_cash=Decimal(1000) + sum((Decimal(p) for p in pnls), Decimal(0)),
        equity_curve=[],
        peak_concurrent=1,
        concurrency_samples=[1],
    )


def test_outlier_removal_reports_what_is_left_without_the_best_trades() -> None:
    row = metrics.row(_result_with(["500", "-10", "-10", "-10"]), name="T", benchmark=False)
    assert row.robustness.normal_pnl == Decimal(470)
    assert row.robustness.ex_best_1_pnl == Decimal(-30)
    assert row.robustness.outlier_dependent
    assert metrics.Flag.OUTLIER_DEPENDENT in row.flags
    assert metrics.Flag.OUTLIER_DOMINATED in row.flags


def test_concentration_is_measured_against_gross_profit() -> None:
    row = metrics.row(_result_with(["100", "50", "25", "-10"]), name="T", benchmark=False)
    assert row.robustness.top_1_share_pct == pytest.approx(
        Decimal("57.142857"), rel=Decimal("1e-4")
    )


def test_a_thin_record_is_flagged_and_shrunk_toward_zero() -> None:
    row = metrics.row(_result_with(["100", "100"]), name="T", benchmark=False)
    assert metrics.Flag.SMALL_SAMPLE in row.flags
    assert row.score_s == Decimal("0.02")
    assert abs(row.lab_score) < abs(row.score_r)


def test_the_ranking_is_not_win_rate() -> None:
    """A strategy that wins constantly but loses money must not rank first."""
    frequent_small_wins = metrics.row(
        _result_with(["1"] * 20 + ["-100"]), name="A", benchmark=False
    )
    rare_large_win = metrics.row(
        _result_with(["200"] + ["-1"] * 20), name="B", benchmark=False
    )
    assert frequent_small_wins.win_rate_pct > rare_large_win.win_rate_pct
    assert metrics.rank([frequent_small_wins, rare_large_win])[0] is rare_large_win


def test_moonshot_capture_uses_the_executable_peak_not_the_printed_one() -> None:
    result = replay.run(
        strategies.S5,
        [
            opportunity(
                [
                    quote(1, "1"),
                    quote(2, "50", liquidity=Decimal(0)),  # a print, not an opportunity
                    quote(400, "1"),
                ]
            )
        ],
    )
    capture = metrics.moonshot_capture(result, Decimal(10))
    assert capture.reached == 0, "a 50x against a dead pool was never reachable"


def test_equity_accounting_closes_over_the_whole_book() -> None:
    opportunities = [
        opportunity(
            [quote(1, "1.4"), quote(2, "0.8"), quote(400, "1.1")],
            mint=f"M{i}",
            at=T0 + timedelta(minutes=i),
        )
        for i in range(12)
    ]
    result = replay.run(strategies.S1, opportunities)
    assert result.final_cash == pytest.approx(
        result.starting_capital + sum((p.net_pnl for p in result.positions), Decimal(0)),
        rel=Decimal("1e-9"),
    )


def test_the_equity_curve_is_marked_to_market_not_to_cost() -> None:
    """A book of positions on their way to zero must show a drawdown."""
    opportunities = [
        opportunity(
            [quote(1, "1"), quote(60, "0.02"), quote(400, "0.02")],
            mint=f"M{i}",
            at=T0 + timedelta(seconds=i),
        )
        for i in range(20)
    ]
    result = replay.run(strategies.S5, opportunities)
    assert metrics.max_drawdown_pct(result.equity_curve, result.starting_capital) > 10
