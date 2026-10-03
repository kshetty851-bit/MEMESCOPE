"""Meme Lifecycle Lab — research parameters as data.

Every number a decision depends on lives here, with its default, so an
experiment can record the exact configuration it ran under (``as_spec()``) and
be reproduced from its row alone.

These defaults are **not tuned**. They are round, a-priori values chosen before
any result was seen; tuning them against the data the Lab will later be judged
on is exactly the selection bias the experiment registry exists to prevent.

Pure: no settings import, no env reads. The service layer may construct a
``LabConfig`` from settings; the engines only ever receive one.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class PortfolioConfig:
    starting_capital: Decimal = Decimal("1000")
    position_size: Decimal = Decimal("10")
    max_open_positions: int = 5
    max_deployed: Decimal = Decimal("50")
    #: Per side, as a fraction (0.003 = 30 bps, the repo-wide fee assumption).
    fee_rate: Decimal = Decimal("0.003")
    #: Applied per side when liquidity is known, on top of constant-product
    #: impact. A floor, because a quote is never the fill.
    slippage_rate: Decimal = Decimal("0.01")
    #: Applied per side when liquidity is unknown (bonding curve, ADR 0002).
    #: Deliberately punitive; the trade is flagged ``cost_model=flat``.
    unknown_liquidity_slippage_rate: Decimal = Decimal("0.03")


@dataclass(frozen=True, slots=True)
class ExitConfig:
    take_profit_multiple: Decimal | None = Decimal("2.0")
    stop_loss_fraction: Decimal | None = Decimal("0.5")  # exit at 0.5x entry
    trailing_stop_fraction: Decimal | None = None  # e.g. 0.3 = 30% off the high
    max_hold: timedelta | None = timedelta(hours=24)
    #: Exit when the 1h attention rate falls below this fraction of the rate
    #: at entry. None disables.
    attention_collapse_fraction: Decimal | None = Decimal("0.25")
    #: Exit when 1h volume falls below this fraction of volume at entry.
    volume_collapse_fraction: Decimal | None = Decimal("0.2")


@dataclass(frozen=True, slots=True)
class AttentionConfig:
    #: Trailing window the baseline rate is measured over, excluding the most
    #: recent ``baseline_gap`` so a spike does not raise its own baseline.
    baseline_window: timedelta = timedelta(days=7)
    baseline_gap: timedelta = timedelta(hours=1)
    #: Below this many total baseline mentions the multiple is Unavailable —
    #: 3 / 0.1 is not "30x attention", it is noise.
    min_baseline_mentions: Decimal = Decimal("5")
    #: A source reading older than this is STALE at as_of.
    max_observation_age: timedelta = timedelta(hours=2)


@dataclass(frozen=True, slots=True)
class EventConfig:
    detector_version: str = "mll-events-v1"
    increase_multiple: Decimal = Decimal("2")
    acceleration_threshold: Decimal = Decimal("1.5")
    #: Revival: the meme was quiet (rate below ``dormant_multiple`` × its
    #: longer-run baseline) for at least ``dormant_for`` and is now above
    #: ``revival_multiple``.
    dormant_multiple: Decimal = Decimal("0.5")
    dormant_for: timedelta = timedelta(days=2)
    revival_multiple: Decimal = Decimal("3")
    #: A new wave needs attention to have fallen below this fraction of the
    #: previous wave's peak before rising again.
    wave_trough_fraction: Decimal = Decimal("0.4")
    decay_multiple: Decimal = Decimal("0.5")
    #: Price thresholds for divergence cases, as fractional change over the
    #: feature window.
    price_flat_band: Decimal = Decimal("0.05")
    price_up: Decimal = Decimal("0.05")
    price_surge: Decimal = Decimal("0.5")
    price_down: Decimal = Decimal("-0.05")
    attention_strong_up: Decimal = Decimal("3")  # baseline multiple
    attention_down: Decimal = Decimal("0.7")
    attention_strong_down: Decimal = Decimal("0.4")


@dataclass(frozen=True, slots=True)
class BaselineStrategyConfig:
    """Attention Acceleration + Market Confirmation. One strategy, untuned."""

    min_acceleration: Decimal = Decimal("1.5")
    min_baseline_multiple: Decimal = Decimal("3")
    #: Market confirmation: 1h volume growth over the preceding hour.
    min_volume_growth: Decimal = Decimal("1.5")
    #: "Sufficient observable market data".
    max_market_data_age: timedelta = timedelta(minutes=15)
    min_market_points: int = 3
    #: Do not enter after the move: price change over the run-up window.
    max_price_run_up: Decimal = Decimal("0.5")
    run_up_window: timedelta = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class LabConfig:
    portfolio: PortfolioConfig = field(default_factory=PortfolioConfig)
    exits: ExitConfig = field(default_factory=ExitConfig)
    attention: AttentionConfig = field(default_factory=AttentionConfig)
    events: EventConfig = field(default_factory=EventConfig)
    baseline: BaselineStrategyConfig = field(default_factory=BaselineStrategyConfig)
    #: Replay decision cadence.
    decision_interval: timedelta = timedelta(minutes=5)

    def as_spec(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_CONFIG = LabConfig()
