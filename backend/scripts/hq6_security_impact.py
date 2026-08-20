"""HQ-6 impact analysis. READ-ONLY, OFFLINE, AND IT TRADES NOTHING.

Answers one question with measured numbers rather than argument:

    "What would happen if the shared security gate were required?"

It opens no position, closes none, modifies no wallet, and writes nothing
except `token_security_evaluations` rows — which are evidence, not decisions,
and which nothing in the entry path reads.

THE HISTORICAL LIMITATION, STATED UP FRONT
------------------------------------------

For a token bought ten days ago, today's chain state is not entry-time state.
This script therefore splits its historical verdict by whether the fact is
genuinely immutable:

  * mint / freeze authority ACTIVE today  -> was necessarily active at entry.
    `SetAuthority(None)` is irreversible, so an authority that still exists
    cannot have been revoked and then un-revoked. This inference is sound in
    **one direction only** and the script uses it in that direction alone.

  * mint / freeze authority REVOKED today -> says nothing about entry. It may
    have been revoked at any point since. Reported as UNKNOWN-at-entry, never
    as a retroactive pass.

  * venue / liquidity                     -> current only, never historical.

Anything else is UNKNOWN. No PASS is ever manufactured for a past trade.
"""

from __future__ import annotations

import asyncio
import sys
from collections import Counter
from decimal import Decimal

from sqlalchemy import text

from app.db.session import SessionFactory
from app.security.contract import CheckName, CheckStatus
from app.security.service import TokenSecurityService

#: How many current Radar candidates to evaluate. Bounded: each is one RPC.
CANDIDATE_SAMPLE = int(sys.argv[1]) if len(sys.argv) > 1 else 60
#: How many historical paper buys to re-inspect.
HISTORY_SAMPLE = int(sys.argv[2]) if len(sys.argv) > 2 else 60


def _pct(part: int, whole: int) -> str:
    return f"{(part / whole * 100):.1f}%" if whole else "n/a"


async def _rows(session, sql: str, **params):
    return (await session.execute(text(sql), params)).all()


async def current_candidates(session, service) -> dict:
    """The live funnel, measured stage by stage from the real tables."""
    discovered = (await _rows(session, "select count(*) from radar_tokens"))[0][0]
    active = (
        await _rows(session, "select count(*) from radar_tokens where is_active")
    )[0][0]
    priced = (
        await _rows(
            session,
            """
            select count(distinct r.mint_address) from radar_tokens r
            join token_market_snapshots s on s.mint_address = r.mint_address
            where r.is_active
            """,
        )
    )[0][0]

    # The set the paper review actually screens: active Radar rows, by score,
    # capped exactly as `_open_entries` caps them.
    candidates = await _rows(
        session,
        """
        select r.mint_address
        from radar_tokens r
        where r.is_active
        order by r.current_opportunity_score desc
        limit :limit
        """,
        limit=CANDIDATE_SAMPLE,
    )
    mints = [row[0] for row in candidates]

    print(f"\n  evaluating {len(mints)} current candidates through the shared evaluator...")
    results = []
    for index, mint in enumerate(mints, start=1):
        results.append(await service.evaluate_now(mint))
        if index % 10 == 0:
            await session.commit()
            print(f"    {index}/{len(mints)}")
    await session.commit()

    overall = Counter(str(item.overall_status) for item in results)
    per_check: dict[str, Counter] = {}
    fail_reasons: Counter = Counter()
    for item in results:
        for check in item.checks:
            per_check.setdefault(str(check.name), Counter())[str(check.status)] += 1
            if check.status is CheckStatus.FAIL:
                fail_reasons.update(check.reason_codes)

    return {
        "discovered": discovered,
        "active": active,
        "priced": priced,
        "evaluated": len(results),
        "overall": overall,
        "per_check": per_check,
        "fail_reasons": fail_reasons,
        "results": results,
    }


async def historical_buys(session, service) -> dict:
    """Existing live-wallet buys, re-inspected with the immutability rule."""
    rows = await _rows(
        session,
        """
        select p.mint_address, p.status, p.entry_price, p.exit_price,
               p.size_usd, p.opened_at, p.exit_reason
        from paper_positions p
        join paper_wallets w on w.id = p.wallet_id
        where w.generation = 2
        order by p.opened_at desc
        limit :limit
        """,
        limit=HISTORY_SAMPLE,
    )
    print(f"\n  re-inspecting {len(rows)} live-wallet positions...")

    buckets: dict[str, list] = {"FAILED_AT_ENTRY": [], "UNKNOWN": []}
    authority_fail = Counter()
    for index, row in enumerate(rows, start=1):
        evaluation = await service.evaluate_now(row[0])
        mint_auth = evaluation.check(CheckName.MINT_AUTHORITY)
        freeze_auth = evaluation.check(CheckName.FREEZE_AUTHORITY)
        program = evaluation.check(CheckName.TOKEN_PROGRAM)
        extensions = evaluation.check(CheckName.TOKEN_EXTENSIONS)

        # The only sound retroactive claim: a still-active authority, or a
        # dangerous property that cannot have been added after the fact.
        provable_fail = [
            check
            for check in (mint_auth, freeze_auth, program, extensions)
            if check is not None and check.status is CheckStatus.FAIL
        ]
        if provable_fail:
            buckets["FAILED_AT_ENTRY"].append(row)
            for check in provable_fail:
                authority_fail.update(check.reason_codes)
        else:
            # Everything else. Revoked-today proves nothing about entry, and
            # liquidity security was never verified at any point in time.
            buckets["UNKNOWN"].append(row)

        if index % 10 == 0:
            await session.commit()
            print(f"    {index}/{len(rows)}")
    await session.commit()
    return {"buckets": buckets, "authority_fail": authority_fail, "total": len(rows)}


def _performance(rows: list) -> dict:
    closed = [row for row in rows if row[1] == "closed" and row[3] is not None]
    if not closed:
        return {"count": len(rows), "closed": 0}
    wins, pnl = 0, Decimal(0)
    gains, losses = Decimal(0), Decimal(0)
    for _mint, _status, entry, exit_price, size, *_rest in closed:
        ret = (Decimal(exit_price) - Decimal(entry)) / Decimal(entry)
        trade_pnl = ret * Decimal(size)
        pnl += trade_pnl
        if trade_pnl > 0:
            wins += 1
            gains += trade_pnl
        else:
            losses += -trade_pnl
    return {
        "count": len(rows),
        "closed": len(closed),
        "win_rate": f"{wins / len(closed) * 100:.1f}%",
        "net_pnl_usd": f"{pnl:.2f}",
        "profit_factor": (f"{gains / losses:.2f}" if losses > 0 else "n/a (no losses)"),
    }


async def main() -> None:
    async with SessionFactory() as session:
        service = TokenSecurityService(session)

        print("=" * 70)
        print("HQ-6 SECURITY IMPACT ANALYSIS — READ-ONLY")
        print("=" * 70)

        current = await current_candidates(session, service)
        print("\n" + "-" * 70)
        print("CURRENT CANDIDATE SECURITY FUNNEL")
        print("-" * 70)
        print(f"  radar tokens (all time)      {current['discovered']}")
        print(f"  active on radar              {current['active']}")
        print(f"  active and priced            {current['priced']}")
        print(f"  evaluated (sample)           {current['evaluated']}")
        for status in ("VERIFIED", "FAILED", "UNKNOWN"):
            count = current["overall"].get(status, 0)
            print(
                f"    security {status:<9}{count:>5}"
                f"  ({_pct(count, current['evaluated'])})"
            )

        print("\n  PER-CHECK BREAKDOWN")
        for name in (
            CheckName.MINT_AUTHORITY, CheckName.FREEZE_AUTHORITY,
            CheckName.TOKEN_PROGRAM, CheckName.TOKEN_EXTENSIONS,
            CheckName.VENUE, CheckName.LIQUIDITY_SECURITY,
        ):
            counter = current["per_check"].get(str(name), Counter())
            parts = "  ".join(
                f"{status}={counter.get(status, 0)}"
                for status in ("PASS", "FAIL", "UNKNOWN", "NOT_APPLICABLE")
                if counter.get(status, 0)
            )
            print(f"    {name!s:<20} {parts}")

        print("\n  FAILURES BY REASON")
        if current["fail_reasons"]:
            for code, count in current["fail_reasons"].most_common():
                print(f"    {code:<36} {count}")
        else:
            print("    (none — no candidate failed a check)")

        history = await historical_buys(session, service)
        print("\n" + "-" * 70)
        print("EXISTING PAPER TRADE SECURITY ANALYSIS (generation 2, live wallet)")
        print("-" * 70)
        print(f"  positions analysed           {history['total']}")
        print("\n  Under the proposed contract, using ONLY sound retroactive facts:")
        for label, rows in history["buckets"].items():
            stats = _performance(rows)
            print(f"\n    {label}: {stats['count']} positions ({stats['closed']} closed)")
            if stats.get("closed"):
                print(f"      win rate       {stats['win_rate']}")
                print(f"      net PnL        ${stats['net_pnl_usd']}")
                print(f"      profit factor  {stats['profit_factor']}")
        if history["authority_fail"]:
            print("\n  Provable entry-time failures by reason:")
            for code, count in history["authority_fail"].most_common():
                print(f"    {code:<36} {count}")
        print(
            "\n  VERIFIED-at-entry is deliberately absent as a bucket: no historical\n"
            "  position has entry-time evidence, so none can be called verified."
        )

        # What enforcement would cost, from the current sample only.
        print("\n" + "-" * 70)
        print("IF VERIFIED WERE REQUIRED TODAY (from the current sample)")
        print("-" * 70)
        evaluated = current["evaluated"]
        blocked = current["overall"].get("FAILED", 0)
        unknown = current["overall"].get("UNKNOWN", 0)
        verified = current["overall"].get("VERIFIED", 0)
        print(f"  candidates that would pass   {verified} ({_pct(verified, evaluated)})")
        print(f"  blocked as positively unsafe {blocked} ({_pct(blocked, evaluated)})")
        print(f"  blocked as UNKNOWN           {unknown} ({_pct(unknown, evaluated)})")
        unknown_drivers: Counter = Counter()
        for item in current["results"]:
            for check in item.checks:
                if check.status is CheckStatus.UNKNOWN:
                    unknown_drivers[str(check.name)] += 1
        print("\n  what drives UNKNOWN:")
        for name, count in unknown_drivers.most_common():
            print(f"    {name:<24} {count}  ({_pct(count, evaluated)})")


if __name__ == "__main__":
    asyncio.run(main())
