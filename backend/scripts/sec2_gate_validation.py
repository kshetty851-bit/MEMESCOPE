"""SEC-2 validation. READ-ONLY. Creates no position and moves no capital.

Runs live candidates through the *real* entry policy — the same
`entry_policy.decide` the repository invariant enforces — and reports what the
gate would do. It never calls `open_position`, so nothing can be opened by
running this.
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.db.session import SessionFactory
from app.security.contract import (
    EVALUATOR_VERSION,
    CheckName,
    CheckStatus,
    SecurityCheck,
    SecurityStatus,
    TokenSecurityEvaluation,
    roll_up,
)
from app.security.entry_policy import (
    MANDATORY_CHECKS,
    MAX_EVIDENCE_AGE,
    decide,
)
from app.security.service import TokenSecurityService

SAMPLE = int(sys.argv[1]) if len(sys.argv) > 1 else 80


def pct(part: int, whole: int) -> str:
    return f"{part / whole * 100:.1f}%" if whole else "n/a"


def scenarios() -> None:
    """§32's required demonstrations, against the real policy function."""
    now = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)

    def build(**over: SecurityCheck) -> TokenSecurityEvaluation:
        checks = tuple(
            over.get(str(name)) or SecurityCheck(name=name, status=CheckStatus.PASS)
            for name in MANDATORY_CHECKS
        )
        return TokenSecurityEvaluation(
            mint_address="m",
            evaluated_at=now,
            overall_status=roll_up(checks),
            checks=checks,
            evaluator_version=EVALUATOR_VERSION,
        )

    cases = [
        ("fully verified candidate", decide(build(), now=now)),
        (
            "LP_OUTSTANDING candidate",
            decide(
                build(
                    LIQUIDITY_SECURITY=SecurityCheck(
                        name=CheckName.LIQUIDITY_SECURITY,
                        status=CheckStatus.UNKNOWN,
                        reason_codes=("LP_OUTSTANDING",),
                    )
                ),
                now=now,
            ),
        ),
        (
            "unsafe: mint authority active",
            decide(
                build(
                    MINT_AUTHORITY=SecurityCheck(
                        name=CheckName.MINT_AUTHORITY,
                        status=CheckStatus.FAIL,
                        reason_codes=("MINT_AUTHORITY_ACTIVE",),
                    )
                ),
                now=now,
            ),
        ),
        (
            "unsupported venue",
            decide(
                build(
                    VENUE=SecurityCheck(
                        name=CheckName.VENUE,
                        status=CheckStatus.FAIL,
                        reason_codes=("VENUE_UNSUPPORTED",),
                    )
                ),
                now=now,
            ),
        ),
        ("RPC outage (no evaluation at all)", decide(None, now=now)),
        (
            "stale PASS",
            decide(build(), now=now + MAX_EVIDENCE_AGE + timedelta(seconds=1)),
        ),
        (
            "evaluation from an older evaluator",
            decide(
                TokenSecurityEvaluation(
                    mint_address="m",
                    evaluated_at=now,
                    overall_status=SecurityStatus.VERIFIED,
                    checks=tuple(
                        SecurityCheck(name=name, status=CheckStatus.PASS)
                        for name in MANDATORY_CHECKS
                    ),
                    evaluator_version="1.0.0",
                ),
                now=now,
            ),
        ),
    ]
    print("-" * 74)
    print("SCENARIO VALIDATION (real entry policy, no positions created)")
    print("-" * 74)
    for label, decision in cases:
        verdict = "ALLOW " if decision.allowed else "REFUSE"
        print(
            f"  {verdict}  {label:36} {decision.outcome:24} "
            f"{','.join(decision.reason_codes) or '-'}"
        )


async def main() -> None:
    async with SessionFactory() as session:
        print("=" * 74)
        print("SEC-2 SECURITY ENTRY GATE VALIDATION — READ-ONLY")
        print("=" * 74)
        scenarios()

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

        print(f"\n  running {len(mints)} live candidates through the gate...")
        service = TokenSecurityService(session)
        started = time.monotonic()
        decisions = []
        for index, mint in enumerate(mints, start=1):
            now = datetime.now(UTC)
            evaluations = await service.evaluate_candidates([mint], now=now)
            decisions.append(
                (mint, decide(evaluations[0] if evaluations else None, now=now))
            )
            if index % 20 == 0:
                await session.commit()
                print(f"    {index}/{len(mints)}")
        await session.commit()
        elapsed = time.monotonic() - started

        total = len(decisions)
        outcomes = Counter(str(d.outcome) for _m, d in decisions)
        print("\n" + "-" * 74)
        print("CURRENT CANDIDATE SAMPLE THROUGH THE SEC-2 GATE")
        print("-" * 74)
        print(f"  TOTAL OTHERWISE-ELIGIBLE CANDIDATES   {total}")
        labels = {
            "ALLOWED": "VERIFIED / WOULD ENTER",
            "REFUSED_UNSAFE": "FAILED / BLOCKED (unsafe)",
            "REFUSED_UNKNOWN": "UNKNOWN / BLOCKED",
            "REFUSED_UNAVAILABLE": "INFRASTRUCTURE / TEMP BLOCKED",
        }
        for key, label in labels.items():
            count = outcomes.get(key, 0)
            print(f"    {label:32} {count:>4}  ({pct(count, total)})")
        allowed = outcomes.get("ALLOWED", 0)
        print(f"\n  RETENTION  {pct(allowed, total)}")

        reasons: Counter = Counter()
        for _mint, decision in decisions:
            if not decision.allowed:
                reasons.update(decision.reason_codes or ("(none)",))
        print("\n  TOP BLOCK REASONS")
        for code, count in reasons.most_common():
            print(f"    {code:<36} {count}")

        venues = (
            await session.execute(
                text(
                    """
                    select distinct on (s.mint_address) s.mint_address, s.dex_name
                    from token_market_snapshots s
                    where s.mint_address = any(:mints)
                    order by s.mint_address, s.captured_at desc
                    """
                ),
                {"mints": mints},
            )
        ).all()
        venue_of = {row[0]: (row[1] or "none") for row in venues}
        by_venue: dict[str, Counter] = {}
        for mint, decision in decisions:
            by_venue.setdefault(venue_of.get(mint, "none"), Counter())[
                "allowed" if decision.allowed else "blocked"
            ] += 1
        print("\n  BY VENUE")
        for venue, counter in sorted(by_venue.items(), key=lambda kv: -sum(kv[1].values())):
            print(
                f"    {venue:<12} total={sum(counter.values()):<4} "
                f"would_enter={counter.get('allowed', 0):<4} "
                f"blocked={counter.get('blocked', 0)}"
            )

        print(
            f"\n  GATE LATENCY  {elapsed / max(total, 1):.2f}s per candidate "
            f"({elapsed:.0f}s for {total})"
        )
        print("\n  No position was created. No capital moved. No transaction was signed.")


if __name__ == "__main__":
    asyncio.run(main())
