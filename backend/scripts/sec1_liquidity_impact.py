"""SEC-1 impact measurement. READ-ONLY. No signing, no submission, no wallet.

Re-runs the HQ-6 candidate sample through the shared evaluator now that
LIQUIDITY_SECURITY is genuinely verified on-chain, and reports what the two
candidate policies would retain. It enables neither.
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections import Counter

from sqlalchemy import text

from app.db.session import SessionFactory
from app.security.contract import CheckName, CheckStatus, SecurityStatus
from app.security.service import TokenSecurityService

SAMPLE = int(sys.argv[1]) if len(sys.argv) > 1 else 80
OPEN_AUDIT = "--open-positions" in sys.argv


def pct(part: int, whole: int) -> str:
    return f"{part / whole * 100:.1f}%" if whole else "n/a"


async def evaluate(session, service, mints, label):
    print(f"\n  evaluating {len(mints)} {label}...")
    started = time.monotonic()
    results = []
    for index, mint in enumerate(mints, start=1):
        results.append(await service.evaluate_now(mint))
        if index % 10 == 0:
            await session.commit()
            print(f"    {index}/{len(mints)}")
    await session.commit()
    elapsed = time.monotonic() - started
    print(f"    done in {elapsed:.1f}s  ({elapsed / max(len(mints), 1):.2f}s per token)")
    return results, elapsed


def report(results, title):
    total = len(results)
    print("\n" + "-" * 70)
    print(title)
    print("-" * 70)
    overall = Counter(str(item.overall_status) for item in results)
    print(f"  TOTAL      {total}")
    for status in ("VERIFIED", "FAILED", "UNKNOWN"):
        count = overall.get(status, 0)
        print(f"    {status:<9} {count:>4}  ({pct(count, total)})")

    print("\n  LIQUIDITY_SECURITY by status and mechanism")
    by_status: Counter = Counter()
    by_mech: Counter = Counter()
    liq_reasons: Counter = Counter()
    for item in results:
        check = item.check(CheckName.LIQUIDITY_SECURITY)
        if check is None:
            continue
        by_status[str(check.status)] += 1
        by_mech[str(check.evidence.get("mechanism"))] += 1
        if check.status is not CheckStatus.PASS:
            liq_reasons.update(check.reason_codes)
    for status, count in by_status.most_common():
        print(f"    {status:<16} {count:>4}  ({pct(count, total)})")
    print("  mechanisms:")
    for mech, count in by_mech.most_common():
        print(f"    {mech:<30} {count:>4}")
    print("  liquidity UNKNOWN/FAIL reasons:")
    for code, count in liq_reasons.most_common():
        print(f"    {code:<36} {count:>4}")

    print("\n  BY TRADED VENUE")
    venue_rows: dict[str, Counter] = {}
    for item in results:
        venue = str(item.evidence.get("venue") or "none").lower()
        venue_rows.setdefault(venue, Counter())[str(item.overall_status)] += 1
    for venue, counter in sorted(venue_rows.items(), key=lambda kv: -sum(kv[1].values())):
        total_v = sum(counter.values())
        print(
            f"    {venue:<12} total={total_v:<4} "
            f"verified={counter.get('VERIFIED', 0):<4} "
            f"failed={counter.get('FAILED', 0):<4} "
            f"unknown={counter.get('UNKNOWN', 0)}"
        )

    print("\n  FAILURES BY REASON (whole evaluation)")
    fails: Counter = Counter()
    for item in results:
        if item.overall_status is SecurityStatus.FAILED:
            for check in item.checks:
                if check.status is CheckStatus.FAIL:
                    fails.update(check.reason_codes)
    for code, count in fails.most_common() or [("(none)", 0)]:
        print(f"    {code:<36} {count}")
    return total


def policies(results):
    """What each candidate policy would retain. Neither is enabled."""
    core = (
        CheckName.MINT_AUTHORITY,
        CheckName.FREEZE_AUTHORITY,
        CheckName.TOKEN_PROGRAM,
        CheckName.TOKEN_EXTENSIONS,
        CheckName.VENUE,
    )
    total = len(results)
    hybrid = strict = 0
    for item in results:
        core_ok = True
        for name in core:
            check = item.check(name)
            if check is None or check.status not in (
                CheckStatus.PASS,
                CheckStatus.NOT_APPLICABLE,
            ):
                core_ok = False
                break
        if not core_ok:
            continue
        hybrid += 1
        liquidity = item.check(CheckName.LIQUIDITY_SECURITY)
        if liquidity is not None and liquidity.status is CheckStatus.PASS:
            strict += 1
    print("\n" + "-" * 70)
    print("POLICY RETENTION (MEASURED, NEITHER ENABLED)")
    print("-" * 70)
    print(f"  candidates evaluated                 {total}")
    print(f"  HYBRID C  (liquidity UNKNOWN allowed) {hybrid:>4}  ({pct(hybrid, total)})")
    print(f"  STRICT    (liquidity must PASS)       {strict:>4}  ({pct(strict, total)})")


async def main() -> None:
    async with SessionFactory() as session:
        service = TokenSecurityService(session)
        print("=" * 70)
        print("SEC-1 LIQUIDITY SECURITY IMPACT — READ-ONLY")
        print("=" * 70)

        rows = (
            await session.execute(
                text(
                    """
                    select r.mint_address from radar_tokens r
                    where r.is_active
                    order by r.current_opportunity_score desc
                    limit :limit
                    """
                ),
                {"limit": SAMPLE},
            )
        ).all()
        mints = [row[0] for row in rows]
        results, elapsed = await evaluate(session, service, mints, "current candidates")
        total = report(results, "CURRENT CANDIDATE SECURITY FUNNEL")
        policies(results)
        print(
            f"\n  RPC: 2 getMultipleAccounts + 1 getAccountInfo per token "
            f"(~3 calls), {elapsed / max(total, 1):.2f}s per token"
        )

        if OPEN_AUDIT:
            open_rows = (
                await session.execute(
                    text(
                        """
                        select p.mint_address from paper_positions p
                        join paper_wallets w on w.id = p.wallet_id
                        where w.generation = 2 and p.status = 'open'
                        """
                    )
                )
            ).all()
            open_mints = [row[0] for row in open_rows]
            results, _ = await evaluate(session, service, open_mints, "OPEN paper positions")
            report(results, "OPEN PAPER POSITIONS — *CURRENT* SECURITY, NOT ENTRY-TIME")
            print(
                "\n  These are CURRENT states. They are not entry-time evidence and\n"
                "  must never be read as such. No position was modified."
            )


if __name__ == "__main__":
    asyncio.run(main())
