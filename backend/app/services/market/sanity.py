"""Ingest data-quality firewall: annotate, never delete.

V1 research found a single provider print 4x10^11 times the real price booked
as a winning trade; V4 found glitch prints still reaching `radar_tokens.peak_
multiple` (12 fresh admissions >100x, worst 304,776x). The fix is not to drop
strange rows — raw evidence must stay auditable — but to *flag* them at ingest
so peaks, features, outcomes and wallet reads can exclude them while the row
itself remains exactly what the provider said.

Pure module: no I/O, no clock, no settings read. The caller supplies the
thresholds and the recent context; this decides. That is what makes the rules
testable against synthetic histories and replayable over stored ones.

## How a genuine move is told from a glitch

A single print far outside the recent band is suspect. A *persistent* new
level is not: once enough consecutive recent prints (suspect or not) agree
with each other at the new level, the print is accepted even though it is far
from the accepted median — the market has demonstrably moved. The cost of
this honesty is a short quarantine (the first `min_prior` prints of a genuine
step change are flagged); the benefit is that no lone impossible number can
ever look like a fill again.

Rows that carry no positive price (dead pools, unpriced reads) are never
flagged — a provider saying "nothing here" is evidence, not an anomaly.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

REASON_PRICE_HIGH = "price_band_high"
REASON_PRICE_LOW = "price_band_low"
REASON_LIQUIDITY_JUMP = "liquidity_jump"
REASON_PAIR_SWITCH = "pair_switch"


@dataclass(frozen=True, slots=True)
class PriorPoint:
    """One earlier reading of the same token, newest-last."""

    captured_at: datetime
    price_usd: Decimal | None
    liquidity_usd: Decimal | None
    pool_address: str | None
    suspect: bool


@dataclass(frozen=True, slots=True)
class Verdict:
    suspect: bool
    reason: str | None
    #: The accepted-median baseline the print was judged against — recorded on
    #: the row so the judgement is auditable without rebuilding the window.
    baseline_price_usd: Decimal | None


def _median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return Decimal(statistics.median(values))


def classify(
    *,
    price_usd: Decimal | None,
    liquidity_usd: Decimal | None,
    pool_address: str | None,
    prior: list[PriorPoint],
    band: Decimal,
    liquidity_jump: Decimal,
    min_prior: int,
) -> Verdict:
    """Judge one incoming reading against its recent history.

    `prior` is every stored reading of this token inside the comparison
    window, oldest-first, flagged or not. Only unflagged rows form the
    baseline; flagged rows are still consulted for the persistence rule.
    """
    if price_usd is None or price_usd <= 0:
        return Verdict(False, None, None)

    accepted = [p.price_usd for p in prior if not p.suspect and p.price_usd and p.price_usd > 0]
    baseline = _median(accepted)

    # --- pair switch: same mint, different pool, mid-series -----------------
    # A pool change is a market EVENT (migration, provider re-resolution), and
    # V1 showed it can move price and liquidity by orders of magnitude in one
    # row. Flagged so series readers treat it as a boundary, not a move.
    last_pool = next(
        (p.pool_address for p in reversed(prior) if p.pool_address), None
    )
    if pool_address and last_pool and pool_address != last_pool:
        return Verdict(True, REASON_PAIR_SWITCH, baseline)

    if len(accepted) < min_prior or baseline is None or baseline <= 0:
        # Too little history to judge: pass through. The first minutes of a
        # token's life are unjudgeable by construction, and refusing to store
        # clean-looking rows would starve the very window that later judges.
        return Verdict(False, None, baseline)

    out_of_band_high = price_usd > baseline * band
    out_of_band_low = price_usd * band < baseline
    if out_of_band_high or out_of_band_low:
        # Persistence check: if the most recent `min_prior` prints (flagged or
        # not) already sit at this level, the move is real — accept it.
        recent = [p.price_usd for p in prior[-min_prior:] if p.price_usd and p.price_usd > 0]
        if len(recent) >= min_prior and all(
            r / band <= price_usd <= r * band for r in recent
        ):
            return Verdict(False, None, baseline)
        return Verdict(
            True,
            REASON_PRICE_HIGH if out_of_band_high else REASON_PRICE_LOW,
            baseline,
        )

    # --- liquidity discontinuity --------------------------------------------
    accepted_liq = [
        p.liquidity_usd for p in prior if not p.suspect and p.liquidity_usd and p.liquidity_usd > 0
    ]
    liq_baseline = _median(accepted_liq)
    if (
        liquidity_usd is not None
        and liquidity_usd > 0
        and liq_baseline is not None
        and liq_baseline > 0
        and len(accepted_liq) >= min_prior
        and (liquidity_usd > liq_baseline * liquidity_jump or liquidity_usd * liquidity_jump < liq_baseline)
    ):
        return Verdict(True, REASON_LIQUIDITY_JUMP, baseline)

    return Verdict(False, None, baseline)
