"""Executable outcome truth: what a $10 position could actually have done.

The raw Track Record aggregates provider prints — glitches, unfillable wicks
and drained-pool fantasies included. Research measured the gap: the UI's "34%
reached 2x" is 23.0% when valued as something sellable, and the median final
value after 24h is $0.00. This module computes that executable version, with
the calibrated execution model the research programs converged on:

  * 30 bps protocol fee per side
  * constant-product impact against effective depth = (liquidity/2) / 12 —
    the 12x factor measured against 320 live Karthik Jupiter quotes
  * provider-inactive pool = $0, never the last healthy print
  * ingest-flagged (suspect) rows excluded entirely

Pure: no I/O, no clock, no settings. The worker feeds it stored observations;
`METHOD_VERSION` names the model so a recomputation is a new fact, never a
silent restatement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

METHOD_VERSION = "exec-v1-12x"

FEE = Decimal("0.003")
IMPACT_MULT = Decimal("12")
ENTRY_USD = Decimal("10")


@dataclass(frozen=True, slots=True)
class Reading:
    captured_at: datetime
    price_usd: Decimal | None
    liquidity_usd: Decimal | None
    inactive: bool


@dataclass(frozen=True, slots=True)
class ExecutableOutcome:
    executable_peak_multiple: Decimal | None
    reached_125_24h: bool | None
    reached_2x_24h: bool | None
    reached_2x_72h: bool | None
    final_value_frac_24h: Decimal | None
    decided_24h: bool
    snapshots_used: int


def _entry_quantity(price: Decimal, liquidity: Decimal) -> Decimal | None:
    """Tokens $10 buys at this reading, fee and calibrated impact paid."""
    if price <= 0 or liquidity <= 0:
        return None
    depth = (liquidity / 2) / IMPACT_MULT
    spend = ENTRY_USD * (1 - FEE)
    return spend / (price * (1 + spend / depth))


def _sell_value(quantity: Decimal, price: Decimal, liquidity: Decimal) -> Decimal:
    """What selling the whole position into this reading nets, in USD."""
    if price <= 0 or liquidity <= 0:
        return Decimal(0)
    depth = (liquidity / 2) / IMPACT_MULT
    gross = quantity * price
    return (gross / (1 + gross / depth)) * (1 - FEE)


def compute(
    readings: list[Reading], *, entered_at: datetime, data_end: datetime
) -> ExecutableOutcome | None:
    """First-passage executable value per $1 in, from the admission instant.

    Returns None when no entry was ever fillable — a token that could not be
    bought has no executable outcome, which is itself the honest answer.
    Horizon flags are None (not False) until the horizon has fully elapsed
    inside stored data: an undecidable question is reported as undecided.
    """
    usable = [
        r
        for r in readings
        if r.captured_at >= entered_at
    ]
    entry = next(
        (
            r
            for r in usable
            if not r.inactive
            and r.price_usd is not None
            and r.price_usd > 0
            and r.liquidity_usd is not None
            and r.liquidity_usd > 0
        ),
        None,
    )
    if entry is None:
        return None
    quantity = _entry_quantity(entry.price_usd, entry.liquidity_usd)  # type: ignore[arg-type]
    if quantity is None or quantity <= 0:
        return None

    h24 = entry.captured_at + timedelta(hours=24)
    h72 = entry.captured_at + timedelta(hours=72)
    peak = Decimal(0)
    hit_125_24 = hit_2x_24 = hit_2x_72 = False
    final_24: Decimal | None = None
    last_value: Decimal | None = None
    used = 0

    for r in usable:
        if r.captured_at < entry.captured_at:
            continue
        if r.inactive:
            value = Decimal(0)
        elif r.price_usd is None or r.price_usd <= 0 or r.liquidity_usd is None or r.liquidity_usd <= 0:
            continue
        else:
            value = _sell_value(quantity, r.price_usd, r.liquidity_usd)
        used += 1
        frac = value / ENTRY_USD
        if r.captured_at <= h24:
            last_value = frac
            if frac >= Decimal("1.25"):
                hit_125_24 = True
            if frac >= 2:
                hit_2x_24 = True
        if r.captured_at <= h72 and frac >= 2:
            hit_2x_72 = True
        peak = max(peak, frac)
        if r.inactive:
            # A dead pool ends the trade at $0 for every later horizon.
            if r.captured_at <= h24:
                last_value = Decimal(0)
            break

    decided_24 = data_end >= h24 or any(r.inactive for r in usable)
    if decided_24:
        final_24 = last_value if last_value is not None else Decimal(0)

    return ExecutableOutcome(
        executable_peak_multiple=peak.quantize(Decimal("0.000001")),
        reached_125_24h=hit_125_24 if decided_24 else (True if hit_125_24 else None),
        reached_2x_24h=hit_2x_24 if decided_24 else (True if hit_2x_24 else None),
        reached_2x_72h=hit_2x_72 if (data_end >= h72 or any(r.inactive for r in usable)) else (True if hit_2x_72 else None),
        final_value_frac_24h=(final_24.quantize(Decimal("0.000001")) if final_24 is not None else None),
        decided_24h=decided_24,
        snapshots_used=used,
    )
