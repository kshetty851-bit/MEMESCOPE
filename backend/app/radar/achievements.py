"""Milestones and performance, measured from first detection.

The single rule this module exists to enforce: **returns are calculated from
MEMESCOPE's first detection, never from the token's launch.** Measuring from
launch would credit the platform with moves it never called, which is precisely
the dishonesty the track record exists to rule out. A token that had already
done 50x before the Radar noticed it starts at 1.0x here.

Achievements are permanent. Once a token has touched 5x it has touched 5x, even
if it is subsequently worthless — the track record records what happened, not
what is currently flattering.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from app.radar.models import AchievementTier, Performance

#: The ladder. Append-only: these are persisted in `radar_achievements.tier`.
TIERS: tuple[AchievementTier, ...] = (
    AchievementTier(Decimal(2), "2x"),
    AchievementTier(Decimal(5), "5x"),
    AchievementTier(Decimal(10), "10x"),
    AchievementTier(Decimal(25), "25x"),
    AchievementTier(Decimal(50), "50x"),
    AchievementTier(Decimal(100), "100x"),
    AchievementTier(Decimal(250), "250x"),
    AchievementTier(Decimal(500), "500x"),
    AchievementTier(Decimal(1000), "1000x"),
)

_SECONDS_PER_DAY = Decimal(86_400)


def multiple(first: Decimal | None, current: Decimal | None) -> Decimal | None:
    """`current / first`, or `None` where it is undefined.

    A first price of zero yields `None` rather than infinity. The provider does
    occasionally report zero, and an infinite return would corrupt every
    aggregate on the track record page.
    """
    if first is None or current is None or first <= 0:
        return None
    return current / first


def performance(
    *,
    first_price: Decimal | None,
    current_price: Decimal | None,
    peak_price: Decimal | None,
    detected_at: datetime,
    now: datetime,
) -> Performance:
    """Assemble a token's performance since detection."""
    elapsed = (now - detected_at).total_seconds()
    days = Decimal(max(elapsed, 0)) / _SECONDS_PER_DAY

    return Performance(
        first_price=first_price,
        current_price=current_price,
        peak_price=peak_price,
        current_multiple=multiple(first_price, current_price),
        peak_multiple=multiple(first_price, peak_price),
        days_since_detection=days,
    )


def newly_earned(
    *,
    peak_multiple: Decimal | None,
    already_earned: Sequence[Decimal],
) -> tuple[AchievementTier, ...]:
    """Tiers reached that have not yet been recorded.

    Driven by the **peak** multiple, not the current one, because an
    achievement is a thing that happened. A token that touched 10x and fell back
    to 3x has earned 2x, 5x and 10x, and none of them are revoked.
    """
    if peak_multiple is None:
        return ()

    earned = set(already_earned)
    return tuple(
        tier
        for tier in TIERS
        if peak_multiple >= tier.multiple and tier.multiple not in earned
    )


def tier_for(label: str) -> AchievementTier | None:
    for tier in TIERS:
        if tier.label == label:
            return tier
    return None
