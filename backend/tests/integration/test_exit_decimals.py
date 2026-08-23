"""The exit decimals precedence chain.

12, 13. `_exit_execution_for` needs a mint's decimals to ask Jupiter what the
sell is worth. Without them it falls to the constant-product model. On
2026-08-21 the UOTF exit fell through with "Token decimals unavailable" while
a security evaluation carrying `decimals: 6` for that exact mint had been on
disk for six hours.

The chain is: entry quote → canonical token row → **security evidence** → live
RPC → legacy. This file covers the link that was missing, and every way the
evidence could be wrong rather than merely absent.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.token import DiscoveredToken
from app.models.token_security import TokenSecurityEvaluationRow
from app.paper.service import PaperWalletService

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 21, 15, 25, tzinfo=UTC)
MINT = "U" * 44


async def evaluation(
    session: AsyncSession,
    *,
    evidence: dict[str, Any],
    at: datetime = NOW,
    status: str = "VERIFIED",
    mint: str = MINT,
) -> None:
    session.add(
        TokenSecurityEvaluationRow(
            mint_address=mint,
            evaluated_at=at,
            overall_status=status,
            evaluator_version="1.1.0",
            reason_codes=[],
            checks=[],
            evidence=evidence,
        )
    )
    await session.flush()


async def token(session: AsyncSession, mint: str = MINT) -> DiscoveredToken:
    row = DiscoveredToken(
        mint_address=mint,
        name="Decimals Probe",
        symbol="DEC",
        signature=f"sig-{uuid.uuid4()}",
        slot=1,
    )
    session.add(row)
    await session.flush()
    return row


def service(session: AsyncSession) -> PaperWalletService:
    return PaperWalletService(session)


class TestSecurityEvidenceIsUsed:
    """12. The link that was missing on 2026-08-21."""

    async def test_decimals_are_read_from_security_evidence(
        self, db_session: AsyncSession
    ) -> None:
        await token(db_session)
        await evaluation(db_session, evidence={"decimals": 6, "venue": "pumpswap"})
        assert await service(db_session)._security_evidence_decimals(MINT) == 6

    async def test_old_evidence_is_still_used(self, db_session: AsyncSession) -> None:
        """The specific reason the incident was not fixed by a freshness window.

        UOTF's evaluation was four hours old when its exit needed decimals.
        Decimals are one byte of the mint account written at `InitializeMint`
        and the token program exposes no instruction to change them, so an old
        reading of an immutable field is the same reading, not a stale one.
        """
        mint = "V" * 44
        await token(db_session, mint)
        await evaluation(
            db_session, evidence={"decimals": 6}, at=NOW - timedelta(days=3), mint=mint
        )
        assert await service(db_session)._security_evidence_decimals(mint) == 6

    async def test_a_failed_evaluation_still_supplies_decimals(
        self, db_session: AsyncSession
    ) -> None:
        """A FAILED verdict decoded the mint account exactly as successfully.

        `evidence["decimals"]` is written as `inspection.decimals if inspection
        else None`, so it reflects whether the decode worked and not what the
        verdict was. Filtering on VERIFIED would discard sound readings and buy
        nothing.
        """
        mint = "W" * 44
        await token(db_session, mint)
        await evaluation(
            db_session, evidence={"decimals": 9}, status="FAILED", mint=mint
        )
        assert await service(db_session)._security_evidence_decimals(mint) == 9

    async def test_the_newest_evaluation_with_decimals_wins(
        self, db_session: AsyncSession
    ) -> None:
        mint = "X" * 44
        await token(db_session, mint)
        await evaluation(
            db_session, evidence={"decimals": 6}, at=NOW - timedelta(hours=2), mint=mint
        )
        await evaluation(db_session, evidence={"decimals": 8}, at=NOW, mint=mint)
        assert await service(db_session)._security_evidence_decimals(mint) == 8


class TestMalformedEvidenceIsRejected:
    """13. Every way the field could be wrong rather than merely missing."""

    async def test_no_evidence_at_all_returns_none(
        self, db_session: AsyncSession
    ) -> None:
        assert await service(db_session)._security_evidence_decimals("Y" * 44) is None

    async def test_a_null_decimals_field_is_skipped(
        self, db_session: AsyncSession
    ) -> None:
        """An evaluation whose mint decode failed writes `None` here."""
        mint = "1" * 44
        await token(db_session, mint)
        await evaluation(db_session, evidence={"decimals": None}, mint=mint)
        assert await service(db_session)._security_evidence_decimals(mint) is None

    async def test_a_row_with_decimals_is_preferred_over_a_newer_row_without(
        self, db_session: AsyncSession
    ) -> None:
        """A later failed decode must not mask an earlier good one."""
        mint = "2" * 44
        await token(db_session, mint)
        await evaluation(
            db_session, evidence={"decimals": 6}, at=NOW - timedelta(hours=1), mint=mint
        )
        await evaluation(db_session, evidence={"decimals": None}, at=NOW, mint=mint)
        assert await service(db_session)._security_evidence_decimals(mint) == 6

    async def test_a_string_is_not_coerced(self, db_session: AsyncSession) -> None:
        """`"6"` would survive `int()`, and a malformed row must be refused."""
        mint = "3" * 44
        await token(db_session, mint)
        await evaluation(db_session, evidence={"decimals": "6"}, mint=mint)
        assert await service(db_session)._security_evidence_decimals(mint) is None

    async def test_a_boolean_is_rejected(self, db_session: AsyncSession) -> None:
        """`isinstance(True, int)` is true in Python; `True` would mean 1 decimal."""
        mint = "4" * 44
        await token(db_session, mint)
        await evaluation(db_session, evidence={"decimals": True}, mint=mint)
        assert await service(db_session)._security_evidence_decimals(mint) is None

    async def test_an_implausible_value_is_rejected(
        self, db_session: AsyncSession
    ) -> None:
        """SPL decimals occupy one byte and no real mint exceeds 9.

        A wrong value here would not raise — it would misprice the sell by a
        power of ten, which is the failure mode worth refusing loudly.
        """
        mint = "5" * 44
        await token(db_session, mint)
        await evaluation(db_session, evidence={"decimals": 42}, mint=mint)
        assert await service(db_session)._security_evidence_decimals(mint) is None

    async def test_a_negative_value_is_rejected(self, db_session: AsyncSession) -> None:
        mint = "6" * 44
        await token(db_session, mint)
        await evaluation(db_session, evidence={"decimals": -1}, mint=mint)
        assert await service(db_session)._security_evidence_decimals(mint) is None

    async def test_another_mints_evidence_is_never_used(
        self, db_session: AsyncSession
    ) -> None:
        """Filtered in SQL and re-asserted in Python.

        Decimals from the wrong mint would not fail; they would silently price
        the sell off by a power of ten.
        """
        await token(db_session, "7" * 44)
        await evaluation(db_session, evidence={"decimals": 6}, mint="7" * 44)
        assert await service(db_session)._security_evidence_decimals("8" * 44) is None

    async def test_zero_decimals_is_a_legitimate_value(
        self, db_session: AsyncSession
    ) -> None:
        """Boundary: 0 is valid and must not be rejected as falsy."""
        mint = "9" * 44
        await token(db_session, mint)
        await evaluation(db_session, evidence={"decimals": 0}, mint=mint)
        assert await service(db_session)._security_evidence_decimals(mint) == 0
