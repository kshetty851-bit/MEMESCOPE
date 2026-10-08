"""Meme Lifecycle Lab — the baseline strategy and its control arms.

The strategy's one non-negotiable property: an Unavailable input is never a
pass and never a zero. The run-up guard keeps it from entering after the move.
Control arms are the same conditions recomposed, so they differ from the
baseline only in what they look at.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.lifecycle_lab.config import BaselineStrategyConfig
from app.lifecycle_lab.domain import (
    AgeBucket,
    Arm,
    AttentionFeatures,
    MarketFeatures,
    Measured,
    Unavailable,
    spec_hash,
)
from app.lifecycle_lab.strategy import (
    REASON_CONDITIONS_MET,
    REASON_CONDITIONS_NOT_MET,
    REASON_CONTROL_A_NOT_WIRED,
    REASON_INPUTS_UNAVAILABLE,
    REGISTRY,
    STATUS_NOT_WIRED,
    StrategyInputs,
    decide,
    strategy_spec,
)

pytestmark = pytest.mark.unit

T = datetime(2026, 9, 1, tzinfo=UTC)
CFG = BaselineStrategyConfig()


def attention(**kw: Measured) -> AttentionFeatures:
    base: dict[str, Measured] = {
        "mentions_5m": Decimal(5),
        "mentions_15m": Decimal(15),
        "mentions_1h": Decimal(60),
        "mentions_6h": Decimal(100),
        "mentions_24h": Decimal(200),
        "velocity": Decimal(2),
        "acceleration": Decimal(2),
        "baseline_multiple": Decimal(5),
        "unique_participants": Unavailable("no_source"),
        "engagement": Unavailable("no_source"),
        "platform_count": Decimal(2),
    }
    base.update(kw)
    return AttentionFeatures(as_of=T, meme_id="m1", **base)  # type: ignore[arg-type]


def market(**kw: Measured) -> MarketFeatures:
    base: dict[str, Measured] = {
        "price_usd": Decimal(1),
        "market_cap": Decimal(100000),
        "liquidity_usd": Unavailable("x"),
        "volume_1h": Decimal(5000),
        "volume_growth": Decimal(2),
        "price_change": Decimal("0.1"),
        "liquidity_change": Unavailable("x"),
        "data_age_seconds": Decimal(60),
    }
    base.update(kw)
    return MarketFeatures(  # type: ignore[arg-type]
        as_of=T, mint_address="A", token_age=None, age_bucket=AgeBucket.UNKNOWN, **base
    )


def inputs(
    *, run_up: Measured = Decimal("0.1"), points: int = 5, **kw: Measured
) -> StrategyInputs:
    attn_keys = {"acceleration", "baseline_multiple", "mentions_1h"}
    return StrategyInputs(
        attention=attention(**{k: v for k, v in kw.items() if k in attn_keys}),
        market=market(**{k: v for k, v in kw.items() if k not in attn_keys}),
        run_up=run_up,
        market_points=points,
    )


def test_enters_when_every_condition_holds() -> None:
    d = decide(Arm.BASELINE, inputs(), CFG)
    assert d.enter and d.reason_code == REASON_CONDITIONS_MET and d.failed_conditions == ()


@pytest.mark.parametrize(
    "field", ["acceleration", "baseline_multiple", "volume_growth", "data_age_seconds"]
)
def test_unavailable_is_never_a_pass(field: str) -> None:
    """Every input, made Unavailable, blocks entry with an _unavailable code and
    the source's reason in the evidence — not treated as 0 and not as pass."""
    d = decide(Arm.BASELINE, inputs(**{field: Unavailable("no_source")}), CFG)
    assert not d.enter
    assert d.reason_code == REASON_INPUTS_UNAVAILABLE
    assert any(f.endswith("_unavailable") for f in d.failed_conditions)
    assert {"unavailable": "no_source"} in d.evidence.values()


def test_unavailable_run_up_is_not_a_pass() -> None:
    d = decide(Arm.BASELINE, inputs(run_up=Unavailable("no_reference_point")), CFG)
    assert not d.enter and "price_run_up_unavailable" in d.failed_conditions


def test_run_up_guard_blocks_entry_after_the_move() -> None:
    """Do not enter after the move: +60% in the window is past the 50% cap."""
    d = decide(Arm.BASELINE, inputs(run_up=Decimal("0.6")), CFG)
    assert not d.enter
    assert d.failed_conditions == ("price_run_up_above_max",)
    assert d.reason_code == REASON_CONDITIONS_NOT_MET
    assert decide(Arm.BASELINE, inputs(run_up=Decimal("0.5")), CFG).enter


def test_thresholds_are_inclusive_and_measured() -> None:
    assert decide(Arm.BASELINE, inputs(acceleration=CFG.min_acceleration), CFG).enter
    d = decide(Arm.BASELINE, inputs(acceleration=Decimal("1.49")), CFG)
    assert d.failed_conditions == ("acceleration_below_min",)


def test_stale_market_data_blocks_entry() -> None:
    d = decide(Arm.BASELINE, inputs(data_age_seconds=Decimal(16 * 60)), CFG)
    assert d.failed_conditions == ("market_data_age_above_max",)


def test_too_few_market_points_blocks_entry() -> None:
    d = decide(Arm.BASELINE, inputs(points=2), CFG)
    assert d.failed_conditions == ("market_points_below_min",)


def test_control_b_ignores_attention() -> None:
    d = decide(Arm.CONTROL_B_MARKET_ONLY, inputs(acceleration=Unavailable("no_source")), CFG)
    assert d.enter
    assert "acceleration" not in d.evidence
    assert not decide(Arm.CONTROL_B_MARKET_ONLY, inputs(run_up=Decimal(1)), CFG).enter


def test_control_c_ignores_market_confirmation_but_not_execution() -> None:
    d = decide(
        Arm.CONTROL_C_ATTENTION_ONLY,
        inputs(volume_growth=Unavailable("x"), run_up=Decimal(5), points=0),
        CFG,
    )
    assert d.enter
    stale = decide(Arm.CONTROL_C_ATTENTION_ONLY, inputs(data_age_seconds=Decimal(10**6)), CFG)
    assert not stale.enter


def test_control_d_matches_baseline_conditions() -> None:
    for case in (inputs(), inputs(run_up=Decimal(1)), inputs(acceleration=Unavailable("x"))):
        b = decide(Arm.BASELINE, case, CFG)
        d = decide(Arm.CONTROL_D_COMBINED, case, CFG)
        assert (b.status, b.failed_conditions, b.evidence) == (
            d.status,
            d.failed_conditions,
            d.evidence,
        )


def test_control_a_is_not_wired() -> None:
    d = decide(Arm.CONTROL_A_EXISTING, inputs(), CFG)
    assert not d.enter
    assert d.status == STATUS_NOT_WIRED
    assert d.reason_code == REASON_CONTROL_A_NOT_WIRED
    assert strategy_spec(Arm.CONTROL_A_EXISTING, CFG)["wired"] is False


def test_every_arm_is_registered() -> None:
    assert set(REGISTRY) == set(Arm)


def test_strategy_spec_hash_is_stable_and_sensitive() -> None:
    a = spec_hash(strategy_spec(Arm.BASELINE, CFG))
    assert a == spec_hash(strategy_spec(Arm.BASELINE, BaselineStrategyConfig()))
    assert a != spec_hash(strategy_spec(Arm.CONTROL_D_COMBINED, CFG))
    assert a != spec_hash(
        strategy_spec(Arm.BASELINE, replace(CFG, max_price_run_up=Decimal("0.4")))
    )


def test_no_recommendation_wording_in_reason_codes() -> None:
    """Reason codes describe observations; no buy/sell/hold language."""
    banned = re.compile(r"\b(buy|sell|hold|consider)\b", re.IGNORECASE)
    cases = [inputs(), inputs(run_up=Decimal(2)), inputs(acceleration=Unavailable("x"))]
    for arm in Arm:
        for case in cases:
            d = decide(arm, case, CFG)
            for text in (d.reason_code, d.status, *d.failed_conditions):
                assert not banned.search(text.replace("_", " ")), text
