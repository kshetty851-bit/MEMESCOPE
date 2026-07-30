"""Holder Intelligence — declared, and permanently unavailable.

## Why this file exists at all

Phase 15 asks for six analysts and this is the third. It cannot be built, and
the honest response is to say so in the same shape as the five that can, rather
than quietly shipping five and letting the absence go unmentioned.

## Why it cannot be built

`radar_tokens.first_holder_count` and `radar_snapshots.holder_count` exist in
the schema. Both are **100% null** — 0 of 33 rows and 0 of 74 respectively,
measured on the live database. The columns were reserved for a pipeline that
was never built.

Nothing about ownership can be derived from what the platform does hold. It
stores market aggregates: price, market cap, liquidity, volume and buy/sell
*counts*. A count of trades is not a count of holders — one wallet trading
forty times and forty wallets trading once are indistinguishable in this data,
and they are opposite situations.

Approximating holder growth from trade counts would produce a number with the
shape of evidence and none of the substance, placed exactly where users are
most likely to trust it. That is the failure `lib/intelligence.ts` was deleted
for in Phase 4.1, and the reason `smart_money.py` reports null rather than zero.

## What would make it real

1. A holder-snapshot pipeline (Helius `getTokenAccounts` or an indexer), written
   to a new table on the enrichment cadence.
2. Enough history for "growth" to mean anything — a single holder count is a
   fact, not a trend.

Steps 1 and 2 are a data-engineering project, not a scoring module. Until they
exist this analyst returns `None`, never `0`.
"""

from __future__ import annotations

from app.analysts.base import AnalystId, AnalystMeta, Reading, RiskWarning, Severity
from app.radar.models import RadarSeries

UNAVAILABLE_REASON = (
    "LETZMOON does not collect holder data. The schema reserves columns for it "
    "and they are empty; nothing about ownership can be derived from trade "
    "counts, because one wallet trading forty times and forty wallets trading "
    "once look identical here."
)

META = AnalystMeta(
    id=AnalystId.HOLDERS,
    name="Holder Intelligence",
    question="Is ownership broadening or concentrating?",
    operational=False,
    unavailable_reason=UNAVAILABLE_REASON,
)


def analyse(series: RadarSeries) -> Reading:
    """Always unavailable.

    Takes the series it cannot use, so it satisfies the same signature as every
    other analyst and the orchestrator needs no special case. The day a holder
    pipeline exists, only this file changes.
    """
    return Reading.unavailable(
        AnalystId.HOLDERS,
        reason=UNAVAILABLE_REASON,
        warnings=(
            RiskWarning(
                code="HOLDERS_NOT_COLLECTED",
                severity=Severity.CAUTION,
                message=(
                    "Ownership concentration is unknown. A single wallet may hold "
                    "most of the supply and LETZMOON would not be able to see it, "
                    "so treat the absence of a holder warning as silence rather "
                    "than a clearance."
                ),
            ),
        ),
    )
