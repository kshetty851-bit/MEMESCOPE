"""Reads and one append for shared token-security evidence.

Append-only. There is no update and no delete: a stored evaluation is what
the platform knew at an instant, and rewriting it would destroy the only
thing it is for.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.token_security import TokenSecurityEvaluationRow
from app.security.contract import (
    CheckName,
    CheckStatus,
    SecurityCheck,
    SecurityStatus,
    TokenSecurityEvaluation,
)


def _to_domain(row: TokenSecurityEvaluationRow) -> TokenSecurityEvaluation:
    """Rebuild the frozen contract object from its stored JSON.

    An unrecognised check name or status is dropped rather than coerced: a
    row written by a future evaluator version must not be read back as
    something this version would act on.
    """
    checks: list[SecurityCheck] = []
    for item in row.checks or []:
        try:
            name = CheckName(item["name"])
            status = CheckStatus(item["status"])
        except (KeyError, ValueError, TypeError):
            continue
        checks.append(
            SecurityCheck(
                name=name,
                status=status,
                reason_codes=tuple(item.get("reason_codes") or ()),
                detail=str(item.get("detail") or ""),
                evidence=item.get("evidence") or {},
            )
        )
    return TokenSecurityEvaluation(
        mint_address=row.mint_address,
        evaluated_at=row.evaluated_at,
        overall_status=SecurityStatus(row.overall_status),
        checks=tuple(checks),
        evaluator_version=row.evaluator_version,
        market_snapshot_at=row.market_snapshot_at,
        evidence=row.evidence or {},
    )


class TokenSecurityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, evaluation: TokenSecurityEvaluation) -> None:
        self._session.add(
            TokenSecurityEvaluationRow(
                mint_address=evaluation.mint_address,
                evaluated_at=evaluation.evaluated_at,
                overall_status=str(evaluation.overall_status),
                evaluator_version=evaluation.evaluator_version,
                reason_codes=list(evaluation.reason_codes),
                checks=[check.as_json() for check in evaluation.checks],
                evidence=evaluation.evidence,
                market_snapshot_at=evaluation.market_snapshot_at,
            )
        )
        await self._session.flush()

    @staticmethod
    def _latest_per_mint(mints: Sequence[str]) -> Select[Any]:
        """One row per mint — the newest — in a single round trip.

        `DISTINCT ON` rather than a correlated subquery so a batch read of
        fifty mints stays one index scan. The browser must never need a
        request per Radar row, and the endpoint behind it must never need a
        query per mint either.
        """
        return (
            select(TokenSecurityEvaluationRow)
            .where(TokenSecurityEvaluationRow.mint_address.in_(list(mints)))
            .distinct(TokenSecurityEvaluationRow.mint_address)
            .order_by(
                TokenSecurityEvaluationRow.mint_address,
                TokenSecurityEvaluationRow.evaluated_at.desc(),
            )
        )

    async def latest_for_mint(self, mint: str) -> TokenSecurityEvaluation | None:
        row = (
            await self._session.execute(
                select(TokenSecurityEvaluationRow)
                .where(TokenSecurityEvaluationRow.mint_address == mint)
                .order_by(TokenSecurityEvaluationRow.evaluated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return _to_domain(row) if row else None

    async def latest_for_mints(
        self, mints: Sequence[str]
    ) -> dict[str, TokenSecurityEvaluation]:
        if not mints:
            return {}
        rows = (await self._session.execute(self._latest_per_mint(mints))).scalars().all()
        return {row.mint_address: _to_domain(row) for row in rows}

    async def history_for_mint(
        self, mint: str, *, limit: int = 20
    ) -> list[TokenSecurityEvaluation]:
        rows = (
            (
                await self._session.execute(
                    select(TokenSecurityEvaluationRow)
                    .where(TokenSecurityEvaluationRow.mint_address == mint)
                    .order_by(TokenSecurityEvaluationRow.evaluated_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return [_to_domain(row) for row in rows]

    async def summary_since(self, since: datetime) -> dict[str, Any]:
        """Aggregate for the Atlas panel, computed in SQL.

        Counted over *distinct mints*, not rows: re-evaluating one token forty
        times is not forty tokens reviewed, and an activity figure that says
        otherwise would make a quiet window look busy.
        """
        newest = (
            select(
                TokenSecurityEvaluationRow.mint_address,
                TokenSecurityEvaluationRow.overall_status,
                TokenSecurityEvaluationRow.reason_codes,
            )
            .where(TokenSecurityEvaluationRow.evaluated_at >= since)
            .distinct(TokenSecurityEvaluationRow.mint_address)
            .order_by(
                TokenSecurityEvaluationRow.mint_address,
                TokenSecurityEvaluationRow.evaluated_at.desc(),
            )
            .subquery()
        )
        rows = (await self._session.execute(select(newest))).all()

        counts = dict.fromkeys(
            (SecurityStatus.VERIFIED, SecurityStatus.FAILED, SecurityStatus.UNKNOWN), 0
        )
        by_reason: dict[str, int] = {}
        for _mint, status, reason_codes in rows:
            try:
                counts[SecurityStatus(status)] += 1
            except ValueError:
                continue
            if SecurityStatus(status) is SecurityStatus.FAILED:
                for code in reason_codes or []:
                    by_reason[code] = by_reason.get(code, 0) + 1

        last = (
            await self._session.execute(
                select(func.max(TokenSecurityEvaluationRow.evaluated_at))
            )
        ).scalar_one_or_none()
        total_rows = (
            await self._session.execute(
                select(func.count()).select_from(TokenSecurityEvaluationRow)
            )
        ).scalar_one()

        return {
            "evaluated_recently": len(rows),
            "verified_count": counts[SecurityStatus.VERIFIED],
            "failed_count": counts[SecurityStatus.FAILED],
            "unknown_count": counts[SecurityStatus.UNKNOWN],
            "failures_by_reason": dict(
                sorted(by_reason.items(), key=lambda pair: pair[1], reverse=True)
            ),
            "last_evaluation_at": last,
            "total_evaluations": total_rows,
        }
