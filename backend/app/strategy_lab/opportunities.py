"""The canonical opportunity stream. **Read-only, point-in-time, no backfill.**

§1 of the brief is the whole scientific requirement: every strategy must see
the same opportunity, frozen as it looked at the moment it became one. This
module builds that stream and nothing else.

── WHAT A CANONICAL OPPORTUNITY IS ──────────────────────────────────────────

The **first** `radar_decision_snapshots` row for a mint whose
`eligibility_state` is `ELIGIBLE`. That row is already the platform's own
record of "this token became eligible at this instant, and here is everything
we knew" — it carries the market state, the derived features, the availability
map and the Radar's own scores, all captured together. Rebuilding an
equivalent from `token_market_snapshots` would be re-deriving a decision the
platform already recorded, and would be wrong wherever the two disagreed.

First, not every: a mint that stays eligible for six hours produces hundreds of
rows, and entering the same token repeatedly is not what any of these
strategies do. One mint, one opportunity, ever.

**Deliberately not the Paper Wallet's entries.** Those are the subset of
eligible tokens the live wallet happened to have cash for, which is a
selection biased by the wallet's own sizing and its own timing. Replaying over
them would measure exits against a population chosen by a strategy under test.

── NO BACKFILL ──────────────────────────────────────────────────────────────

Every field on `Opportunity` comes from the eligibility row itself or from
evidence timestamped at or before it. Nothing is filled in from what happened
next; nothing missing is estimated. Absent is `None`, and `None` reaches the
report as "unavailable" rather than as a zero.

── POOL PINNING ─────────────────────────────────────────────────────────────

The forward series is filtered to the pool the token was eligible *on*. A token
that migrates venues is a different instrument with a different book, and
splicing the new pool's prices onto the old position's entry would replay a
trade nobody could have held.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.strategy_lab.rules import EXECUTABLE_FLOOR_USD, Quote

#: Bumped whenever the definition of a canonical opportunity changes. Stored on
#: every persisted opportunity so a mixed-vintage dataset is detectable rather
#: than silently averaged.
CANONICAL_VERSION = "1.0.0"

#: How long past the hold clock to keep reading observations. A position whose
#: six-hour cutoff lands inside a feed outage still needs the next reading to
#: settle against: settling late at an observed price is honest, settling never
#: is an open position that flatters the result.
TAIL = timedelta(hours=2)


class Exclusion:
    """Why a candidate is not usable. Every excluded row carries exactly one."""

    NO_PRICE = "NO_ENTRY_PRICE"
    NO_LIQUIDITY = "NO_ENTRY_LIQUIDITY"
    NO_POOL = "NO_ENTRY_POOL"
    NO_OBSERVATIONS = "NO_FORWARD_OBSERVATIONS"
    NO_EXPIRY_COVERAGE = "NO_OBSERVATION_AT_OR_AFTER_EXPIRY"
    NOT_MATURED = "HOLD_WINDOW_NOT_YET_ELAPSED"


@dataclass(frozen=True, slots=True)
class Opportunity:
    """One frozen eligibility event, and the forward series it can be replayed on.

    Everything above `quotes` is point-in-time evidence. `quotes` is the future,
    and it is the *only* thing here that knows anything about the future — which
    is what lets `no look-ahead` be checked by inspection.
    """

    #: `radar_decision_snapshots.id`. The platform's own identifier for this
    #: decision, reused rather than re-minted so the lineage is traceable.
    source_decision_id: str
    mint_address: str
    eligible_at: datetime

    entry_price: Decimal | None
    liquidity_usd: Decimal | None
    market_cap: Decimal | None
    liq_to_mcap: Decimal | None
    volume_24h: Decimal | None
    volume_1h: Decimal | None
    buys_24h: int | None
    sells_24h: int | None
    buy_sell_ratio_24h: Decimal | None
    pool_address: str | None
    venue: str | None
    trading_pair: str | None

    #: Seconds since this platform first discovered the token. A lower bound on
    #: true token age, and named for what it is. S9's gate reads this.
    discovery_age_seconds: Decimal | None
    first_discovered_at: datetime | None

    radar_rank: int | None
    radar_score: Decimal | None
    confidence_score: Decimal | None
    risk_score: Decimal | None
    risk_band: str | None

    #: SEC-2's verdict as of the most recent evaluation at or before
    #: `eligible_at`. `None` when no evaluation existed yet — never the verdict
    #: SEC-2 reached afterwards.
    security_status: str | None
    security_evaluated_at: datetime | None

    #: Observation cadence and coverage the Radar itself recorded at this
    #: instant. Carried because a strategy's result is only as trustworthy as
    #: the series it was replayed on.
    observation_cadence_seconds: Decimal | None
    radar_input_snapshot_count: int | None
    evidence_coverage_pct: Decimal | None

    quotes: tuple[Quote, ...]
    excluded_reason: str | None = None

    @property
    def usable(self) -> bool:
        return self.excluded_reason is None

    @property
    def utc_day(self) -> str:
        return self.eligible_at.date().isoformat()


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return out


def _int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


_ELIGIBILITY = text(
    """
    SELECT DISTINCT ON (d.mint_address)
           d.id, d.mint_address, d.evaluated_at, d.first_discovered_at,
           d.time_since_discovery_seconds, d.radar_rank, d.radar_score,
           d.confidence_score, d.risk_score, d.risk_band,
           d.market_state, d.derived_features, d.evidence
      FROM radar_decision_snapshots d
     WHERE d.eligibility_state = 'ELIGIBLE'
       AND (CAST(:since AS timestamptz) IS NULL
            OR d.evaluated_at >= CAST(:since AS timestamptz))
       AND (CAST(:until AS timestamptz) IS NULL
            OR d.evaluated_at <= CAST(:until AS timestamptz))
     ORDER BY d.mint_address, d.evaluated_at
    """
)

#: Point-in-time SEC-2. `<=` the eligibility instant, latest first: the verdict
#: that existed when the decision was made, never one reached later.
_SECURITY = text(
    """
    SELECT DISTINCT ON (s.mint_address)
           s.mint_address, s.overall_status, s.evaluated_at
      FROM token_security_evaluations s
      JOIN (SELECT unnest(CAST(:mints AS text[])) AS mint,
                   unnest(CAST(:times AS timestamptz[])) AS cutoff) c
        ON c.mint = s.mint_address AND s.evaluated_at <= c.cutoff
     ORDER BY s.mint_address, s.evaluated_at DESC
    """
)

#: **Point-in-time valuation, from the observation table.**
#:
#: The Radar's `market_state` does not carry a market cap — the provider block it
#: stores has price, liquidity, volume and trade counts and nothing else. Without
#: this join `market_cap` and `liq_to_mcap` were NULL on every canonical
#: opportunity, so any research question about valuation was unanswerable.
#:
#: `captured_at <= :cutoff` and latest-first, exactly as the SEC-2 join does: the
#: most recent observation that existed *before* the decision. Measured over the
#: live set the lag averages 11 seconds, so this is the same instant in practice
#: and never a value from after it.
_VALUATION = text(
    """
    SELECT DISTINCT ON (s.mint_address)
           s.mint_address, s.market_cap, s.fully_diluted_valuation
      FROM token_market_snapshots s
      JOIN (SELECT unnest(CAST(:mints AS text[])) AS mint,
                   unnest(CAST(:times AS timestamptz[])) AS cutoff) c
        ON c.mint = s.mint_address AND s.captured_at <= c.cutoff
     ORDER BY s.mint_address, s.captured_at DESC
    """
)

_QUOTES = text(
    """
    SELECT mint_address, captured_at, price_usd, liquidity_usd, pool_address
      FROM token_market_snapshots
     WHERE mint_address = ANY(CAST(:mints AS text[]))
       AND price_usd IS NOT NULL
       AND price_usd > 0
       AND captured_at >= :start
       AND captured_at <= :end
     ORDER BY mint_address, captured_at
    """
)


async def load(
    session: AsyncSession,
    *,
    hold_for: timedelta = timedelta(hours=6),
    since: datetime | None = None,
    until: datetime | None = None,
    now: datetime | None = None,
) -> list[Opportunity]:
    """Every canonical opportunity in the window, usable and excluded alike.

    Excluded rows are returned rather than dropped: §8 asks for a reason for
    every exclusion, and a loader that filtered silently could not supply one.
    """
    rows = (await session.execute(_ELIGIBILITY, {"since": since, "until": until})).all()
    if not rows:
        return []

    mints = [r.mint_address for r in rows]
    security = {
        s.mint_address: (s.overall_status, s.evaluated_at)
        for s in (
            await session.execute(
                _SECURITY, {"mints": mints, "times": [r.evaluated_at for r in rows]}
            )
        ).all()
    }

    valuation = {
        v.mint_address: (_dec(v.market_cap), _dec(v.fully_diluted_valuation))
        for v in (
            await session.execute(
                _VALUATION, {"mints": mints, "times": [r.evaluated_at for r in rows]}
            )
        ).all()
    }

    window_end = max(r.evaluated_at for r in rows) + hold_for + TAIL
    series: dict[str, list[tuple[datetime, Decimal, Decimal | None, str | None]]] = {}
    for q in (
        await session.execute(
            _QUOTES,
            {
                "mints": mints,
                "start": min(r.evaluated_at for r in rows),
                "end": window_end,
            },
        )
    ).all():
        series.setdefault(q.mint_address, []).append(
            (q.captured_at, Decimal(q.price_usd), _dec(q.liquidity_usd), q.pool_address)
        )

    cutoff = now
    out: list[Opportunity] = []
    for row in rows:
        out.append(
            _build(
                row,
                security.get(row.mint_address),
                valuation.get(row.mint_address),
                series,
                hold_for,
                cutoff,
            )
        )
    out.sort(key=lambda o: o.eligible_at)
    return out


def _build(
    row: Any,
    security: tuple[str, datetime] | None,
    valuation: tuple[Decimal | None, Decimal | None] | None,
    series: dict[str, list[tuple[datetime, Decimal, Decimal | None, str | None]]],
    hold_for: timedelta,
    now: datetime | None,
) -> Opportunity:
    market: dict[str, Any] = row.market_state or {}
    derived: dict[str, Any] = row.derived_features or {}
    evidence: dict[str, Any] = row.evidence or {}

    price = _dec(market.get("price_usd"))
    liquidity = _dec(market.get("liquidity_usd"))
    # `market_state` first because it is the decision's own record; the
    # point-in-time observation is the fallback that actually supplies it.
    mcap = (
        _dec(market.get("market_cap"))
        or _dec(market.get("fully_diluted_valuation"))
        or (valuation[0] if valuation else None)
        or (valuation[1] if valuation else None)
    )
    pool = market.get("pool")
    expires_at = row.evaluated_at + hold_for

    raw = series.get(row.mint_address, [])
    # Pool pinning. A quote from a different pool is a different instrument.
    pinned = [
        q
        for q in raw
        if row.evaluated_at <= q[0] <= expires_at + TAIL and (pool is None or q[3] == pool)
    ]
    quotes = tuple(
        Quote(
            price_usd=q[1],
            captured_at=q[0],
            liquidity_usd=q[2],
            executable=q[2] is not None and q[2] >= EXECUTABLE_FLOOR_USD,
        )
        for q in pinned
    )

    excluded: str | None = None
    if price is None or price <= 0:
        excluded = Exclusion.NO_PRICE
    elif pool is None:
        excluded = Exclusion.NO_POOL
    elif liquidity is None:
        excluded = Exclusion.NO_LIQUIDITY
    elif not quotes:
        excluded = Exclusion.NO_OBSERVATIONS
    elif now is not None and expires_at > now:
        # Not a data problem — the position simply has not finished yet. Kept
        # apart from NO_EXPIRY_COVERAGE so "the feed dropped it" and "it is
        # still running" are never counted as the same failure.
        excluded = Exclusion.NOT_MATURED
    elif not any(q.captured_at >= expires_at for q in quotes):
        excluded = Exclusion.NO_EXPIRY_COVERAGE

    return Opportunity(
        source_decision_id=str(row.id),
        mint_address=row.mint_address,
        eligible_at=row.evaluated_at,
        entry_price=price,
        liquidity_usd=liquidity,
        market_cap=mcap,
        liq_to_mcap=(liquidity / mcap if liquidity is not None and mcap else None),
        volume_24h=_dec(market.get("volume_24h")),
        volume_1h=_dec(market.get("volume_1h")),
        buys_24h=_int(market.get("buys_24h")),
        sells_24h=_int(market.get("sells_24h")),
        buy_sell_ratio_24h=_dec(derived.get("buy_sell_ratio_24h")),
        pool_address=pool,
        venue=market.get("dex"),
        trading_pair=market.get("trading_pair"),
        discovery_age_seconds=_dec(row.time_since_discovery_seconds),
        first_discovered_at=row.first_discovered_at,
        radar_rank=row.radar_rank,
        radar_score=_dec(row.radar_score),
        confidence_score=_dec(row.confidence_score),
        risk_score=_dec(row.risk_score),
        risk_band=row.risk_band,
        security_status=security[0] if security else None,
        security_evaluated_at=security[1] if security else None,
        observation_cadence_seconds=_dec(derived.get("median_observation_cadence_seconds")),
        radar_input_snapshot_count=_int(derived.get("radar_input_snapshot_count")),
        evidence_coverage_pct=_dec(evidence.get("coverage")),
        quotes=quotes,
        excluded_reason=excluded,
    )
