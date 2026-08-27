"""Ask what the open book could actually be sold for.

The Lab values an open position with a CPMM approximation over the REPORTED
`liquidity_usd`. That is fine while the reported figure describes a working pool
and badly wrong once it does not: `618dCC…` fell from $727,062 of liquidity at
entry to $1,722 and was still marked at $3.07 against a $3.00 cost, because a $3
position looks negligible even against $1,722. Jupiter would have paid nothing.

So this asks Jupiter instead. Once every few minutes, for the mints the Lab is
actually holding, at the size it is actually holding — and writes the answer where
`settle` can read it.

## Why this is not a rule change

`is_dead` and the mark are FACTS the frozen exits consume, not rules. Every
strategy already closes on `dead_zero`; none of them were firing because nothing
had told them the position was dead. Correcting a measurement the rules read is
not the same as changing the rules, and `SPEC_HASH` is untouched — which matters,
because a running tournament whose rules changed mid-flight would be worthless.

## Conservative where it is approximate

One quote per MINT, taken at the largest open quantity, then applied per position
as a realisable price per token. Impact rises with size, so a smaller position
would really get a slightly better fill than this credits it with. The error is in
the direction of understating the book, which is the correct direction to be wrong
about money that has not been realised.

Rate limits are real: Jupiter's lite API answers `429` under load, and a refused
quote read as "no route" would condemn a healthy token. A failure here records
nothing rather than recording a death.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.lab import spec
from app.models.lab import LabPosition, LabStrategy, LabTournament
from app.models.research_data import ResearchQuote
from app.models.token import DiscoveredToken
from app.services.jupiter import JupiterExecutionClient

logger = get_logger(__name__)

#: USDC is a six-decimal mint; the token is whatever it is.
USDC_DECIMALS = 6

#: Written on the rows this module produces, so a mark-refresh quote is never
#: confused with the research sample the checkpoint sweep collects.
CONTEXT = "lab_open_mark"

#: How old a quote may be and still be used to mark a position. Longer than the
#: 15-second guard a real order uses, because this values a book rather than
#: authorising a spend — but short enough that a collapse is caught within a
#: couple of ticks.
MAX_QUOTE_AGE = timedelta(minutes=12)

#: When the sweep renews a quote. SHORTER than `MAX_QUOTE_AGE`, deliberately.
#:
#: The sweep used to skip anything still usable, which meant a quote was only
#: renewed AFTER it had already expired — so every mint spent the gap between
#: expiry and the next pass uncovered. Measured on live data: one mint quoted at
#: 02:42, 02:57, 03:12 — a fifteen-minute rhythm against a twelve-minute window,
#: leaving it unusable for three minutes of every cycle. Twenty-six of
#: twenty-eight mints were covered at any instant and the two that were not held
#: enough value to drag mark quality to 60%.
#:
#: Refresh-ahead fixes it: renew at eight minutes, stay valid to twelve, and the
#: four minutes of headroom is more than one sweep cadence. Raising the per-run
#: limit would have changed nothing — it was never the binding constraint.
REFRESH_AFTER = timedelta(minutes=8)

#: Seconds between quotes. Measured, not guessed: 0.2s produced `429 Too Many
#: Requests` on essentially every call, and every one of those would have looked
#: like a dead token.
QUOTE_INTERVAL_SECONDS = 1.3

#: Below this fraction of cost, a position is treated as unsellable rather than
#: cheap. Not a stop loss — the position may be worth exactly this — it is the
#: point at which "you cannot get out" stops being distinguishable from "it is
#: worth nothing", and every frozen strategy already exits on `dead_zero`.
DEAD_FRACTION = Decimal("0.02")


async def refresh(session: AsyncSession, *, now: datetime | None = None,
                  limit: int = 40) -> dict[str, int]:
    """Re-quote the mints the Lab holds open. Writes rows; decides nothing."""
    now = now or datetime.now(UTC)
    # Scoped to the CURRENT tournament. Unscoped, the sweep spent its per-run
    # budget quoting a dormant record's open positions — V6 1.0.0 carried 158 of
    # them — and the live book competed for what was left. It is not biting today
    # only because that record has since closed out, which is the worst kind of
    # not-biting: the bug is fixed by luck and returns the next time a version is
    # bumped with positions still open.
    rows = list((await session.execute(
        select(LabPosition.mint_address,
               LabPosition.token_id,
               LabPosition.quantity,
               LabPosition.size_usd)
        .join(LabStrategy, LabStrategy.id == LabPosition.strategy_row_id)
        .join(LabTournament, LabTournament.id == LabStrategy.tournament_id)
        .where(LabPosition.status == "open",
               LabTournament.spec_version == spec.SPEC_VERSION)
    )).all())
    if not rows:
        return {"mints": 0, "quoted": 0, "failed": 0, "skipped_fresh": 0}

    # Largest quantity per mint: the worst case is the honest one to price.
    largest: dict[str, tuple] = {}
    for mint, token_id, qty, size in rows:
        q = Decimal(str(qty or 0))
        if q <= 0:
            continue
        if mint not in largest or q > largest[mint][1]:
            largest[mint] = (token_id, q, Decimal(str(size or 0)))

    # REFRESH_AFTER, not MAX_QUOTE_AGE: renew before expiry, not after it.
    fresh_cutoff = now - REFRESH_AFTER
    already = {
        m for (m,) in (await session.execute(
            select(ResearchQuote.mint_address).where(
                ResearchQuote.context == CONTEXT,
                ResearchQuote.side == "sell",
                ResearchQuote.requested_at >= fresh_cutoff,
            ).distinct()
        )).all()
    }
    pending = [m for m in largest if m not in already][:limit]

    decimals = {
        m: d for m, d in (await session.execute(
            select(DiscoveredToken.mint_address, DiscoveredToken.decimals)
            .where(DiscoveredToken.mint_address.in_(pending))
        )).all()
    } if pending else {}

    client = JupiterExecutionClient()
    quoted = failed = 0
    for mint in pending:
        token_id, qty, size = largest[mint]
        record = dict(mint_address=mint, token_id=token_id,
                      requested_at=datetime.now(UTC), size_usd=size,
                      context=CONTEXT)
        try:
            sell = await client.sell_quote(
                input_mint=mint, quantity=qty,
                input_decimals=int(decimals.get(mint) or 6), now=now,
            )
            session.add(ResearchQuote(
                **record, side="sell", ok=True,
                in_amount_raw=Decimal(sell.input_amount_raw),
                out_amount_raw=Decimal(sell.output_amount_raw),
                price_impact_pct=sell.price_impact_pct,
                route=(sell.route or "")[:255],
            ))
            quoted += 1
        except Exception as exc:  # noqa: BLE001
            # A refusal here is NOT recorded as a death. Rate limiting and a dead
            # pool raise the same way, and condemning a healthy token because
            # Jupiter was busy would be the worse error by far.
            logger.info("lab_sellability_quote_failed", mint=mint,
                        error=type(exc).__name__)
            failed += 1
        await asyncio.sleep(QUOTE_INTERVAL_SECONDS)

    return {"mints": len(largest), "quoted": quoted, "failed": failed,
            "skipped_fresh": len(already)}


async def realisable_price(
    session: AsyncSession, mint: str, *, now: datetime
) -> Decimal | None:
    """USD per whole token this mint could actually be SOLD at, or None.

    None means nobody asked recently enough to know — the caller keeps its
    existing model rather than inventing a death.
    """
    row = (await session.execute(
        select(ResearchQuote.in_amount_raw, ResearchQuote.out_amount_raw,
               ResearchQuote.ok, DiscoveredToken.decimals)
        .join(DiscoveredToken,
              DiscoveredToken.mint_address == ResearchQuote.mint_address)
        .where(ResearchQuote.mint_address == mint,
               ResearchQuote.context == CONTEXT,
               ResearchQuote.side == "sell",
               ResearchQuote.requested_at >= now - MAX_QUOTE_AGE)
        .order_by(ResearchQuote.requested_at.desc())
        .limit(1)
    )).first()
    if row is None or not row.ok:
        return None
    tokens_raw = Decimal(str(row.in_amount_raw or 0))
    usdc_raw = Decimal(str(row.out_amount_raw or 0))
    if tokens_raw <= 0:
        return None
    # The two sides carry DIFFERENT decimals, so the raw ratio is not a price:
    # USDC is 6dp and the token is its own. Convert both to whole units first.
    token_decimals = int(row.decimals if row.decimals is not None else 6)
    tokens = tokens_raw / (Decimal(10) ** token_decimals)
    usdc = usdc_raw / (Decimal(10) ** USDC_DECIMALS)
    return (usdc / tokens) if tokens > 0 else None


__all__ = ["CONTEXT", "DEAD_FRACTION", "MAX_QUOTE_AGE", "realisable_price", "refresh"]
