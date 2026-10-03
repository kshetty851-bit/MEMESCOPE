"""Meme Lifecycle Lab — exit rules.

Each rule fires on what was observed, fills honestly (stops at the observed
price, targets at the target), and an ambiguous reading resolves adverse-first.
Missing data is never a trigger.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.lifecycle_lab.config import ExitConfig, PortfolioConfig
from app.lifecycle_lab.domain import DataClass, ExitReason, MarketPoint, Measured, Unavailable
from app.lifecycle_lab.exits import (
    EXIT_ORDER,
    PositionExitState,
    evaluate_attention_collapse,
    evaluate_exit,
    side_cost,
)

pytestmark = pytest.mark.unit

T0 = datetime(2026, 9, 1, tzinfo=UTC)
NONE_CFG = ExitConfig(
    take_profit_multiple=None,
    stop_loss_fraction=None,
    trailing_stop_fraction=None,
    max_hold=None,
    attention_collapse_fraction=None,
    volume_collapse_fraction=None,
)


def pos(
    *,
    entry: str = "1",
    peak: str | None = None,
    volume: Measured = Decimal("1000"),
    attention: Measured = Decimal("100"),
) -> PositionExitState:
    return PositionExitState(
        entry_at=T0,
        entry_price=Decimal(entry),
        peak_price=Decimal(peak or entry),
        entry_volume_1h=volume,
        entry_attention_1h=attention,
    )


def pt(price: str | None, minutes: int = 5, volume: str | None = "1000") -> MarketPoint:
    at = T0 + timedelta(minutes=minutes)
    return MarketPoint(
        mint_address="A",
        observed_at=at,
        available_at=at,
        data_class=DataClass.FORWARD,
        price_usd=None if price is None else Decimal(price),
        volume_1h=None if volume is None else Decimal(volume),
    )


def test_take_profit_fills_at_target_not_at_gap() -> None:
    """A limit fills at the level it asked for; booking a gap's upside would
    be the stop-at-trigger error in the other direction."""
    ev = evaluate_exit(
        position=pos(), point=pt("3.5"), cfg=replace(NONE_CFG, take_profit_multiple=Decimal(2))
    )
    assert ev.signal is not None
    assert ev.signal.reason is ExitReason.TAKE_PROFIT
    assert ev.signal.fill_price == Decimal(2)
    assert ev.signal.observed_price == Decimal("3.5")


def test_stop_loss_fills_at_observed_gap() -> None:
    ev = evaluate_exit(
        position=pos(),
        point=pt("0.2"),
        cfg=replace(NONE_CFG, stop_loss_fraction=Decimal("0.5")),
    )
    assert ev.signal is not None and ev.signal.reason is ExitReason.STOP_LOSS
    assert ev.signal.fill_price == Decimal("0.2")
    assert ev.signal.trigger_price == Decimal("0.5")


def test_trailing_stop_measures_against_prior_high() -> None:
    cfg = replace(NONE_CFG, trailing_stop_fraction=Decimal("0.3"))
    ev = evaluate_exit(position=pos(peak="2"), point=pt("1.5"), cfg=cfg)
    assert ev.signal is None  # 1.5 > 2 * 0.7
    ev = evaluate_exit(position=pos(peak="2"), point=pt("1.4"), cfg=cfg)
    assert ev.signal is not None and ev.signal.reason is ExitReason.TRAILING_STOP
    assert ev.signal.fill_price == Decimal("1.4")


def test_peak_advances_only_when_nothing_closed() -> None:
    ev = evaluate_exit(position=pos(), point=pt("1.7"), cfg=NONE_CFG)
    assert ev.signal is None and ev.peak_price == Decimal("1.7")


def test_max_hold_fires_on_first_reading_past_expiry() -> None:
    cfg = replace(NONE_CFG, max_hold=timedelta(hours=1))
    assert evaluate_exit(position=pos(), point=pt("1", minutes=59), cfg=cfg).signal is None
    ev = evaluate_exit(position=pos(), point=pt("1.1", minutes=60), cfg=cfg)
    assert ev.signal is not None and ev.signal.reason is ExitReason.MAX_HOLD
    assert ev.signal.fill_price == Decimal("1.1")


def test_volume_collapse() -> None:
    cfg = replace(NONE_CFG, volume_collapse_fraction=Decimal("0.2"))
    assert evaluate_exit(position=pos(), point=pt("1", volume="200"), cfg=cfg).signal is None
    ev = evaluate_exit(position=pos(), point=pt("1", volume="199"), cfg=cfg)
    assert ev.signal is not None and ev.signal.reason is ExitReason.VOLUME_COLLAPSE


def test_attention_collapse() -> None:
    cfg = replace(NONE_CFG, attention_collapse_fraction=Decimal("0.25"))
    ev = evaluate_exit(position=pos(), point=pt("1"), cfg=cfg, attention_1h=Decimal("24"))
    assert ev.signal is not None and ev.signal.reason is ExitReason.ATTENTION_COLLAPSE
    ev = evaluate_exit(position=pos(), point=pt("1"), cfg=cfg, attention_1h=Decimal("25"))
    assert ev.signal is None


def test_attention_collapse_is_stamped_when_attention_was_known() -> None:
    """The exit cannot predate the attention reading that caused it."""
    cfg = replace(NONE_CFG, attention_collapse_fraction=Decimal("0.25"))
    later = T0 + timedelta(minutes=10)
    ev = evaluate_exit(
        position=pos(),
        point=pt("1", minutes=5),
        cfg=cfg,
        attention_1h=Decimal("0"),
        attention_as_of=later,
    )
    assert ev.signal is not None and ev.signal.at == later
    ev2 = evaluate_attention_collapse(
        position=pos(),
        point=pt("1", minutes=5),
        attention_1h=Decimal("0"),
        attention_as_of=later,
        cfg=cfg,
    )
    assert ev2.signal is not None and ev2.signal.at == later


@pytest.mark.parametrize(
    ("entry", "now"),
    [
        (Unavailable("no_source"), Decimal("0")),
        (Decimal("100"), Unavailable("no_source")),
    ],
)
def test_unavailable_attention_never_triggers_and_is_recorded(
    entry: Measured, now: Measured
) -> None:
    """Absence is never zero: an unmeasured attention rate is not a collapse."""
    cfg = replace(NONE_CFG, attention_collapse_fraction=Decimal("0.25"))
    ev = evaluate_exit(position=pos(attention=entry), point=pt("1"), cfg=cfg, attention_1h=now)
    assert ev.signal is None
    assert any(n.startswith("attention_collapse_unavailable:") for n in ev.notes)
    assert "no_source" in ev.notes[0]


def test_unchecked_attention_is_not_a_note() -> None:
    """``None`` means not evaluated on this reading — different from Unavailable."""
    cfg = replace(NONE_CFG, attention_collapse_fraction=Decimal("0.25"))
    ev = evaluate_exit(position=pos(), point=pt("1"), cfg=cfg, attention_1h=None)
    assert ev.signal is None and ev.notes == ()


def test_unavailable_volume_never_triggers() -> None:
    cfg = replace(NONE_CFG, volume_collapse_fraction=Decimal("0.2"))
    ev = evaluate_exit(position=pos(), point=pt("1", volume=None), cfg=cfg)
    assert ev.signal is None and ev.notes
    ev = evaluate_exit(
        position=pos(volume=Unavailable("x")), point=pt("1", volume="0"), cfg=cfg
    )
    assert ev.signal is None and ev.notes


def test_no_price_never_fills_even_when_expired() -> None:
    cfg = replace(NONE_CFG, max_hold=timedelta(minutes=1))
    ev = evaluate_exit(position=pos(), point=pt(None, minutes=120), cfg=cfg)
    assert ev.signal is None and ev.notes == ("no_price",)


def test_adverse_first_when_one_reading_breaches_several_rules() -> None:
    """A reading that is both past expiry and over target is an expiry; one
    that breaches the stop and has collapsed attention is a stop. The target
    is always last, so ambiguity never books a win."""
    assert EXIT_ORDER[-1] is ExitReason.TAKE_PROFIT
    assert EXIT_ORDER[0] is ExitReason.MAX_HOLD
    full = ExitConfig(
        take_profit_multiple=Decimal(2),
        stop_loss_fraction=Decimal("0.5"),
        trailing_stop_fraction=Decimal("0.3"),
        max_hold=timedelta(hours=1),
        attention_collapse_fraction=Decimal("0.25"),
        volume_collapse_fraction=Decimal("0.2"),
    )
    ev = evaluate_exit(position=pos(), point=pt("5", minutes=61), cfg=full)
    assert ev.signal is not None and ev.signal.reason is ExitReason.MAX_HOLD
    ev = evaluate_exit(
        position=pos(), point=pt("0.4", volume="1"), cfg=full, attention_1h=Decimal(0)
    )
    assert ev.signal is not None and ev.signal.reason is ExitReason.STOP_LOSS
    # Over target AND attention collapsed → attention collapse, not a win.
    ev = evaluate_exit(position=pos(), point=pt("5"), cfg=full, attention_1h=Decimal(0))
    assert ev.signal is not None and ev.signal.reason is ExitReason.ATTENTION_COLLAPSE
    # Over target AND volume collapsed → volume collapse.
    ev = evaluate_exit(position=pos(), point=pt("5", volume="1"), cfg=full)
    assert ev.signal is not None and ev.signal.reason is ExitReason.VOLUME_COLLAPSE


def test_flat_costs_when_liquidity_unknown() -> None:
    cfg = PortfolioConfig()
    cost = side_cost(Decimal("10"), None, cfg)
    assert cost.cost_model == "flat"
    assert cost.total == Decimal("10") * (cfg.fee_rate + cfg.unknown_liquidity_slippage_rate)


def test_constant_product_costs_reuse_paper_costs() -> None:
    cfg = PortfolioConfig()
    cost = side_cost(Decimal("100"), Decimal("2000"), cfg)
    assert cost.cost_model == "constant_product"
    # impact = S * S / (liq / 2) = 100 * 100 / 1000
    assert cost.impact_usd == Decimal("10")
    assert cost.fee_usd == Decimal("0.3")
    assert cost.slippage_usd == Decimal("1")
