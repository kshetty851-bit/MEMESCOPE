"""PW-LIFECYCLE-1 frozen-position audit. READ-ONLY.

Classifies every open position belonging to an archived generation. It closes
nothing, writes nothing, and invents no exit: it replays each position over
the market observations the platform already stored and reports what the exit
engine *would* find.

Classification:

  LEGITIMATELY_OPEN        observations exist since entry and no rule was breached
  HISTORICALLY_RECOVERABLE observations exist and a barrier/expiry was breached
                           at a known past time and price
  UNRESOLVED               no usable observation since entry, so nothing can
                           be said either way
"""

from __future__ import annotations

import asyncio
from collections import Counter
from decimal import Decimal

from sqlalchemy import text

from app.db.session import SessionFactory


async def main() -> None:
    async with SessionFactory() as session:
        rows = (
            await session.execute(
                text(
                    """
                    select w.generation, w.strategy_id, p.id, p.mint_address,
                           p.opened_at, p.entry_price, p.size_usd,
                           p.target_price, p.stop_price, p.expires_at,
                           p.trailing_drawdown, p.last_evaluated_at
                    from paper_positions p
                    join paper_wallets w on w.id = p.wallet_id
                    where p.status = 'open' and w.archived_at is not null
                    order by w.generation, p.opened_at
                    """
                )
            )
        ).all()

        print("=" * 74)
        print("FROZEN POSITION AUDIT — READ-ONLY, NOTHING IS CLOSED")
        print("=" * 74)
        print(f"  positions in archived generations: {len(rows)}")

        buckets: Counter = Counter()
        by_generation: dict[int, Counter] = {}
        recoverable_detail: list[tuple] = []

        for row in rows:
            (
                generation, _strategy, _pid, mint, _opened_at, entry, size,
                target, stop, expires_at, trailing, watermark,
            ) = row

            series = (
                await session.execute(
                    text(
                        """
                        select captured_at, price_usd
                        from token_market_snapshots
                        where mint_address = :mint
                          and captured_at > :since
                          and price_usd is not null and price_usd > 0
                        order by captured_at asc
                        """
                    ),
                    {"mint": mint, "since": watermark},
                )
            ).all()

            outcome = "UNRESOLVED"
            detail = None
            hit = "HISTORICALLY_RECOVERABLE"
            if series:
                peak = Decimal(entry)
                outcome = "LEGITIMATELY_OPEN"
                for captured_at, price in series:
                    price = Decimal(price)
                    peak = max(peak, price)
                    if target is not None and price >= Decimal(target):
                        outcome, detail = hit, ("target", captured_at, price)
                        break
                    if stop is not None and price <= Decimal(stop):
                        outcome, detail = hit, ("stop", captured_at, price)
                        break
                    if (
                        trailing is not None
                        and peak > 0
                        and price <= peak * (Decimal(1) - Decimal(trailing))
                    ):
                        outcome, detail = hit, ("trail", captured_at, price)
                        break
                    if expires_at is not None and captured_at >= expires_at:
                        outcome, detail = hit, ("expiry", captured_at, price)
                        break
                else:
                    if expires_at is not None and series[-1][0] >= expires_at:
                        outcome = hit
                        detail = ("expiry", series[-1][0], Decimal(series[-1][1]))

            buckets[outcome] += 1
            by_generation.setdefault(generation, Counter())[outcome] += 1
            if detail:
                recoverable_detail.append((generation, mint, size, *detail))

        print("\n  CLASSIFICATION")
        for name in ("LEGITIMATELY_OPEN", "HISTORICALLY_RECOVERABLE", "UNRESOLVED"):
            print(f"    {name:<26} {buckets.get(name, 0):>4}")

        print("\n  BY GENERATION")
        for generation, counter in sorted(by_generation.items()):
            print(
                f"    gen {generation}: open={counter.get('LEGITIMATELY_OPEN', 0):<4} "
                f"recoverable={counter.get('HISTORICALLY_RECOVERABLE', 0):<4} "
                f"unresolved={counter.get('UNRESOLVED', 0)}"
            )

        if recoverable_detail:
            reasons = Counter(item[3] for item in recoverable_detail)
            print("\n  RECOVERABLE BY RULE BREACHED")
            for reason, count in reasons.most_common():
                print(f"    {reason:<10} {count}")
            print("\n  EARLIEST FIVE (generation, mint, size, rule, when, price)")
            for item in sorted(recoverable_detail, key=lambda x: x[4])[:5]:
                print(
                    f"    gen {item[0]}  {item[1][:12]}..  ${item[2]}  "
                    f"{item[3]:<7} {item[4]:%Y-%m-%d %H:%M}  {item[5]:.10f}"
                )

        print(
            "\n  Nothing was closed and no P&L was written. These are what the exit\n"
            "  engine would find in already-stored observations, at their own\n"
            "  historical prices — never at today's price."
        )


if __name__ == "__main__":
    asyncio.run(main())
