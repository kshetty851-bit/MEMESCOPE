"""Builders for scoring test inputs.

The engine takes plain dataclasses, so tests construct their inputs directly -
no database, no fixtures, no mocks. That is the practical payoff of keeping
`FeatureSet` free of ORM types, and it is why these helpers are twenty lines
rather than a fixture hierarchy.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.services.scoring.features import FeatureSet, Observation

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def dec(value: str | int | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def observations(
    *,
    count: int = 6,
    liquidity: str | int | None = 50000,
    price: str | int | None = "0.001",
    spacing_seconds: int = 300,
    now: datetime = NOW,
) -> tuple[Observation, ...]:
    """A window of evenly spaced observations, newest first."""
    return tuple(
        Observation(
            captured_at=now - timedelta(seconds=spacing_seconds * index),
            price_usd=dec(price),
            liquidity_usd=dec(liquidity),
        )
        for index in range(count)
    )


def features(**overrides: Any) -> FeatureSet:
    """A healthy, well-observed token. Override one field to isolate a signal."""
    values: dict[str, Any] = {
        "mint_address": "MintTest",
        "evaluated_at": NOW,
        "age_minutes": Decimal(180),
        "tier": "young",
        "tier_interval_seconds": 300,
        "history_window_seconds": 3600,
        "risk_window_seconds": 3600,
        "metadata_resolved": True,
        "latest_snapshot_at": NOW,
        "trading_status": "trading",
        "price_usd": Decimal("0.001"),
        "liquidity_usd": Decimal(50000),
        "market_cap": Decimal(500000),
        "fully_diluted_valuation": Decimal(550000),
        "volume_24h": Decimal(20000),
        "volume_1h": Decimal(2000),
        "volume_5m": Decimal(200),
        "buy_count_24h": 300,
        "sell_count_24h": 200,
        "window": observations(),
        "prior_elite_streak": 0,
    }
    values.update(overrides)
    return FeatureSet(**values)


def declining_window(
    *,
    peak: int,
    current: int,
    seconds_ago: int,
    now: datetime = NOW,
) -> tuple[Observation, ...]:
    """A window whose liquidity peaked `seconds_ago` and has since collapsed.

    The gap between peak and now is what separates a rug in progress from slow
    decay, so it is the parameter tests vary.
    """
    return (
        Observation(
            captured_at=now, price_usd=Decimal("0.001"), liquidity_usd=Decimal(current)
        ),
        Observation(
            captured_at=now - timedelta(seconds=seconds_ago),
            price_usd=Decimal("0.002"),
            liquidity_usd=Decimal(peak),
        ),
    )
