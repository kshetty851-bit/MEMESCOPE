"""HQ-6 read models: the Atlas aggregate, the batch, and the bounds.

Every route here is read-only by construction, and two of these tests exist
to keep it that way — an endpoint that could trigger an evaluation would be an
unauthenticated way to make the platform issue arbitrary RPC calls.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.token_security import TokenSecurityEvaluationRow
from app.security.contract import CheckName, CheckStatus
from app.security.repository import TokenSecurityRepository

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


def row(
    mint: str, status: str, *, at: datetime = NOW, reasons=()
) -> TokenSecurityEvaluationRow:
    return TokenSecurityEvaluationRow(
        mint_address=mint,
        evaluated_at=at,
        overall_status=status,
        evaluator_version="1.0.0",
        reason_codes=list(reasons),
        # Mirrors what `TokenSecurityRepository.record` actually writes: the
        # stored `reason_codes` column is the denormalised roll-up of the
        # per-check codes, so a fixture that put them only on the column would
        # test a row the system cannot produce.
        checks=[
            {
                "name": str(CheckName.MINT_AUTHORITY),
                "status": str(CheckStatus.FAIL if reasons else CheckStatus.PASS),
                "reason_codes": list(reasons),
                "detail": "active" if reasons else "revoked",
                "evidence": {},
            }
        ],
        evidence={},
        market_snapshot_at=None,
    )


class TestSummary:
    async def test_empty_platform_reports_real_zeros_and_says_so(
        self, client, db_session: AsyncSession
    ) -> None:
        """The most dangerous response in the feature.

        Zero verified / zero failed is byte-identical to a perfectly clean
        platform if only the counts are read. `source_state` is what makes
        them distinguishable, so it must be present and correct.
        """
        response = await client.get("/api/v1/token-security/summary")
        assert response.status_code == 200
        body = response.json()
        assert body["verified_count"] == 0
        assert body["failed_count"] == 0
        assert body["unknown_count"] == 0
        assert body["source_state"] == "no_evaluations"
        assert body["last_evaluation_at"] is None

    async def test_counts_distinct_mints_not_rows(
        self, client, db_session: AsyncSession
    ) -> None:
        """Re-evaluating one token forty times is not forty tokens reviewed."""
        now = datetime.now(UTC)
        for offset in range(4):
            db_session.add(
                row("A" * 44, "UNKNOWN", at=now - timedelta(minutes=offset))
            )
        db_session.add(row("B" * 44, "FAILED", at=now, reasons=["VENUE_UNSUPPORTED"]))
        await db_session.commit()

        body = (await client.get("/api/v1/token-security/summary")).json()
        assert body["evaluated_recently"] == 2
        assert body["unknown_count"] == 1
        assert body["failed_count"] == 1
        assert body["failures_by_reason"] == {"VENUE_UNSUPPORTED": 1}
        assert body["source_state"] == "live"

    async def test_evidence_older_than_its_window_reports_stale_not_live(
        self, client, db_session: AsyncSession
    ) -> None:
        db_session.add(
            row("C" * 44, "UNKNOWN", at=datetime.now(UTC) - timedelta(days=3))
        )
        await db_session.commit()
        body = (await client.get("/api/v1/token-security/summary?window_hours=168")).json()
        assert body["source_state"] == "stale"


class TestBatch:
    async def test_one_request_answers_many_mints(
        self, client, db_session: AsyncSession
    ) -> None:
        mints = [chr(ord("a") + index) * 44 for index in range(5)]
        for mint in mints:
            db_session.add(row(mint, "UNKNOWN"))
        await db_session.commit()

        body = (
            await client.get(
                "/api/v1/token-security/evaluations", params={"mints": ",".join(mints)}
            )
        ).json()
        assert body["returned"] == 5
        assert set(body["items"]) == set(mints)

    async def test_a_mint_with_no_evidence_is_named_rather_than_silently_dropped(
        self, client, db_session: AsyncSession
    ) -> None:
        known, unknown = "k" * 44, "u" * 44
        db_session.add(row(known, "UNKNOWN"))
        await db_session.commit()

        body = (
            await client.get(
                "/api/v1/token-security/evaluations",
                params={"mints": f"{known},{unknown}"},
            )
        ).json()
        assert unknown in body["without_evidence"]
        assert unknown not in body["items"]

    async def test_batch_is_bounded_and_reports_the_truncation(
        self, client, db_session: AsyncSession
    ) -> None:
        """A silently shortened answer reads exactly like a complete one."""
        over = settings.TOKEN_SECURITY_MAX_BATCH + 10
        mints = ",".join(f"{index:044d}" for index in range(over))
        body = (
            await client.get(
                "/api/v1/token-security/evaluations", params={"mints": mints}
            )
        ).json()
        assert body["truncated"] is True
        assert body["limit"] == settings.TOKEN_SECURITY_MAX_BATCH
        assert len(body["without_evidence"]) <= settings.TOKEN_SECURITY_MAX_BATCH


class TestPerMint:
    async def test_returns_newest_first_with_per_check_detail(
        self, client, db_session: AsyncSession
    ) -> None:
        mint = "m" * 44
        db_session.add(row(mint, "UNKNOWN", at=NOW - timedelta(hours=2)))
        db_session.add(row(mint, "FAILED", at=NOW, reasons=["MINT_AUTHORITY_ACTIVE"]))
        await db_session.commit()

        body = (
            await client.get(
                f"/api/v1/token-security/evaluations/{mint}", params={"history": 5}
            )
        ).json()
        assert body["items"][0]["overall_status"] == "FAILED"
        assert body["items"][0]["reason_codes"] == ["MINT_AUTHORITY_ACTIVE"]
        assert body["items"][0]["checks"][0]["name"] == "MINT_AUTHORITY"
        # Staleness is answered server-side so no client re-derives the rule.
        assert "stale" in body["items"][0]

    async def test_unknown_mint_answers_an_empty_list_not_an_error(
        self, client
    ) -> None:
        body = (await client.get("/api/v1/token-security/evaluations/" + "z" * 44)).json()
        assert body["items"] == []


class TestTheseRoutesCannotAct:
    async def test_no_write_verb_is_exposed(self, client) -> None:
        for path in (
            "/api/v1/token-security/summary",
            "/api/v1/token-security/evaluations",
        ):
            for verb in (client.post, client.put, client.delete, client.patch):
                assert (await verb(path)).status_code in {404, 405}

    async def test_reading_a_mint_does_not_create_an_evaluation(
        self, client, db_session: AsyncSession
    ) -> None:
        """The read model must never be a way to make the platform call RPC."""
        mint = "n" * 44
        before = await TokenSecurityRepository(db_session).history_for_mint(mint)
        await client.get(f"/api/v1/token-security/evaluations/{mint}")
        after = await TokenSecurityRepository(db_session).history_for_mint(mint)
        assert len(before) == len(after) == 0


class TestRepositoryReconstruction:
    async def test_an_unrecognised_check_is_dropped_rather_than_coerced(
        self, db_session: AsyncSession
    ) -> None:
        """A row from a future evaluator must not be acted on by this one."""
        mint = "f" * 44
        db_session.add(
            TokenSecurityEvaluationRow(
                mint_address=mint,
                evaluated_at=NOW,
                overall_status="UNKNOWN",
                evaluator_version="9.9.9",
                reason_codes=[],
                checks=[
                    {
                        "name": "SOMETHING_NEW", "status": "PASS",
                        "reason_codes": [], "detail": "", "evidence": {},
                    },
                    {
                        "name": "MINT_AUTHORITY", "status": "PASS",
                        "reason_codes": [], "detail": "", "evidence": {},
                    },
                ],
                evidence={},
            )
        )
        await db_session.commit()

        item = await TokenSecurityRepository(db_session).latest_for_mint(mint)
        assert item is not None
        assert [check.name for check in item.checks] == [CheckName.MINT_AUTHORITY]


class TestExecutionPosture:
    """The Execution Vault's only source. Read-only, and structurally so."""

    async def test_reports_locked_when_execution_is_disabled(self, client) -> None:
        body = (await client.get("/api/v1/real-wallet-safety/execution-posture")).json()
        assert body["state"] == "LOCKED"
        assert body["execution_enabled"] is False
        assert body["sourced"] is True

    async def test_exposes_no_key_balance_or_signer_material(self, client) -> None:
        """It answers 'can execution happen', never anything that would help."""
        body = (await client.get("/api/v1/real-wallet-safety/execution-posture")).json()
        blob = str(body).lower()
        for banned in ("public_key", "secret", "signer", "balance", "lamports", "private"):
            assert banned not in blob, banned

    async def test_has_no_write_verb(self, client) -> None:
        path = "/api/v1/real-wallet-safety/execution-posture"
        for verb in (client.post, client.put, client.delete, client.patch):
            assert (await verb(path)).status_code in {404, 405}

    async def test_an_active_kill_switch_halts_regardless_of_configuration(
        self, client, db_session
    ) -> None:
        """HALTED outranks everything: it is the most restrictive state."""
        from app.models.real_wallet_execution import RealWalletKillSwitch

        db_session.add(RealWalletKillSwitch(kind="global", active=True, reason="test"))
        await db_session.commit()
        body = (await client.get("/api/v1/real-wallet-safety/execution-posture")).json()
        assert body["state"] == "HALTED"
        assert body["active_kill_switches"] == 1
