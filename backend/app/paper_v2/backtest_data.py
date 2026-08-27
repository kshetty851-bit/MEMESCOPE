"""Loads the candidate stream and its observations. Read-only.

The candidate stream is **the entries the live trailing-stop lineage actually
took**. Those are exactly the opportunities that passed the shared eligibility
and SEC-2 gates, so replaying V2 over them changes the money management and
nothing else — which is the whole point of the experiment.

Its limit is stated rather than hidden: opportunities V1 *declined for cash*
are not in this stream, because a declined entry stores no price series to
replay. Capture rate is therefore measured against what V1 took, not against
everything the Radar ever ranked.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.paper_v2.ladder import Quote
from app.paper_v2.replay import EXECUTABLE_FLOOR_USD, Candidate

#: Which wallets' entries form the stream. The trailing-stop capital lineage.
LINEAGE_STRATEGIES = (
    "trailing_stop_25_v1",
    "trailing_stop_25_secured_v2",
    "trailing_stop_25_secured_hold6h_v3",
)

_CANDIDATES = text(
    """
    SELECT DISTINCT ON (p.mint_address)
           p.mint_address, p.opened_at, p.entry_price,
           p.entry_liquidity_usd, p.entry_market_cap
      FROM paper_positions p
      JOIN paper_wallets w ON w.id = p.wallet_id
     WHERE w.strategy_id = ANY(:strategies)
       AND p.entry_price > 0
     ORDER BY p.mint_address, p.opened_at
    """
)

_QUOTES = text(
    """
    SELECT mint_address, captured_at, price_usd, liquidity_usd
      FROM token_market_snapshots
     WHERE mint_address = ANY(:mints)
       AND price_usd IS NOT NULL
       AND captured_at >= :start AND captured_at <= :end
     ORDER BY mint_address, captured_at
    """
)


async def load_candidates(
    session: AsyncSession, *, hold_hours: int = 6, tail_hours: int = 2
) -> list[Candidate]:
    """Every distinct token the lineage entered, with its forward price series.

    `tail_hours` extends the window past the expiry so a position whose six-hour
    cutoff falls inside a feed outage still has the next observation available
    to settle against — settling late at an observed price is honest, while
    settling never is an unresolved position that flatters the result.
    """
    rows = (await session.execute(_CANDIDATES, {"strategies": list(LINEAGE_STRATEGIES)})).all()
    if not rows:
        return []

    mints = [row.mint_address for row in rows]
    start = min(row.opened_at for row in rows)
    end = max(row.opened_at for row in rows) + timedelta(hours=hold_hours + tail_hours)

    series: dict[str, list[Quote]] = {}
    for q in (await session.execute(_QUOTES, {"mints": mints, "start": start, "end": end})).all():
        liq = Decimal(q.liquidity_usd) if q.liquidity_usd is not None else None
        series.setdefault(q.mint_address, []).append(
            Quote(
                price_usd=Decimal(q.price_usd),
                captured_at=q.captured_at,
                liquidity_usd=liq,
                executable=liq is not None and liq >= EXECUTABLE_FLOOR_USD,
            )
        )

    out: list[Candidate] = []
    for row in rows:
        window_end = row.opened_at + timedelta(hours=hold_hours + tail_hours)
        quotes = [
            q
            for q in series.get(row.mint_address, [])
            if row.opened_at <= q.captured_at <= window_end
        ]
        out.append(
            Candidate(
                mint_address=row.mint_address,
                offered_at=row.opened_at,
                entry_price=Decimal(row.entry_price),
                entry_liquidity_usd=(
                    Decimal(row.entry_liquidity_usd)
                    if row.entry_liquidity_usd is not None
                    else None
                ),
                entry_market_cap=(
                    Decimal(row.entry_market_cap) if row.entry_market_cap is not None else None
                ),
                quotes=tuple(quotes),
            )
        )
    out.sort(key=lambda c: c.offered_at)
    return out
