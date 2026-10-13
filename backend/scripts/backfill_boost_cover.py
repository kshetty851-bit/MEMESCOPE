"""One-off (Karthik, 2026-10-13): fill grad_boost_picks.has_cover for picks made
before the lab read cover pictures, from DexScreener's profile as it is now.
A coin DexScreener no longer lists stays NULL (unknown, so still bought).

    python -m scripts.backfill_boost_cover           # dry run
    python -m scripts.backfill_boost_cover --apply
"""
from __future__ import annotations

import asyncio
import sys

import httpx
from sqlalchemy import text

from app.db.session import SessionFactory


async def main(apply: bool) -> None:
    async with SessionFactory() as db:
        mints = list((await db.execute(text(
            "select mint from grad_boost_picks where has_cover is null"))).scalars())
        found: dict[str, bool] = {}
        async with httpx.AsyncClient(timeout=20) as client:
            for i in range(0, len(mints), 30):
                r = await client.get("https://api.dexscreener.com/tokens/v1/solana/"
                                     + ",".join(mints[i:i + 30]))
                r.raise_for_status()
                for pair in r.json():
                    m = pair["baseToken"]["address"]
                    found[m] = found.get(m, False) or bool((pair.get("info") or {}).get("header"))
                await asyncio.sleep(1.1)
        print(f"picks without an answer {len(mints)} | listed {len(found)} | "
              f"cover {sum(found.values())} | no cover {sum(not v for v in found.values())} | "
              f"unlisted (left NULL) {len(mints) - len(found)}")
        if apply and found:
            await db.execute(text("""
                update grad_boost_picks p set has_cover = v.c
                from unnest(cast(:m as varchar[]), cast(:c as boolean[])) as v(mint, c)
                where p.mint = v.mint and p.has_cover is null"""),
                {"m": list(found), "c": list(found.values())})
            await db.commit()
            print("applied")


if __name__ == "__main__":
    asyncio.run(main("--apply" in sys.argv))
