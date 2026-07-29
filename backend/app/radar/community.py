"""Community signals — declared, weighted, and not yet collectable.

Twitter/X activity, Telegram and Discord engagement, website uptime and
development cadence are genuine opportunity signals and the Radar declares real
weight for them. It cannot read any of them: the platform integrates no social
API, and there is no credential for one.

This module exists so that absence is **visible in every score** rather than
silently missing from the weight table. It is the same mechanism the scoring
engine uses for `contract_safety` and `smart_money`, and the reason coverage —
and therefore confidence — reads below 100 across the whole Radar.

The consequence is deliberate and worth stating plainly: **the Strong Community
category cannot currently be awarded.** A category that can never be reached is
better than one awarded on invented evidence, and the API reports it as
unreachable rather than merely never appearing.

Implementing this means adding a social provider behind the same abstraction the
market provider uses (ADR 0001), not calling an API from here.
"""

from __future__ import annotations

from app.radar.models import (
    DimensionResult,
    RadarDimension,
    RadarReason,
    RadarSeries,
)


def evaluate(series: RadarSeries) -> DimensionResult:
    """Always unavailable. See the module docstring."""
    del series  # No input can change this answer until a provider exists.
    return DimensionResult.unavailable(
        RadarDimension.COMMUNITY,
        reason=RadarReason.COMMUNITY_DATA_UNAVAILABLE,
    )
