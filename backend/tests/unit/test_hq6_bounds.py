"""HQ-6 must not become an RPC storm or an N+1.

The security evaluator shares a worker with market enrichment and the paper
review. Every bound it relies on is asserted here rather than trusted, because
the failure mode — a sweep that quietly starves the lanes that feed the wallet
— looks like general slowness rather than like this feature.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import settings
from app.security.contract import (
    CHECK_FRESHNESS,
    EVALUATION_FRESHNESS,
    CheckName,
    CheckStatus,
    SecurityCheck,
    TokenSecurityEvaluation,
    roll_up,
)
from app.security.repository import TokenSecurityRepository
from app.security.service import TokenSecurityService

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


class FakeRepository:
    def __init__(self, cached: dict[str, TokenSecurityEvaluation]) -> None:
        self._cached = cached
        self.recorded: list[str] = []

    async def latest_for_mints(self, mints):
        return {m: self._cached[m] for m in mints if m in self._cached}

    async def record(self, evaluation):
        self.recorded.append(evaluation.mint_address)


class CountingEvaluator:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def evaluate(self, *, mint_address: str, now=None):
        self.calls.append(mint_address)
        checks = (SecurityCheck(name=CheckName.VENUE, status=CheckStatus.PASS),)
        return TokenSecurityEvaluation(
            mint_address=mint_address,
            evaluated_at=now or NOW,
            overall_status=roll_up(checks),
            checks=checks,
        )


def service_with(
    cached=None,
) -> tuple[TokenSecurityService, CountingEvaluator, FakeRepository]:
    service = TokenSecurityService.__new__(TokenSecurityService)
    evaluator = CountingEvaluator()
    repository = FakeRepository(cached or {})
    service._session = None
    service._evaluator = evaluator
    service._repository = repository
    return service, evaluator, repository


def fresh_evaluation(mint: str, at: datetime = NOW) -> TokenSecurityEvaluation:
    checks = (SecurityCheck(name=CheckName.VENUE, status=CheckStatus.PASS),)
    return TokenSecurityEvaluation(
        mint_address=mint, evaluated_at=at, overall_status=roll_up(checks), checks=checks
    )


class TestFanOutIsCapped:
    async def test_one_pass_never_exceeds_the_configured_cap(self) -> None:
        service, evaluator, _ = service_with()
        mints = [
            f"{index:044d}"
            for index in range(settings.TOKEN_SECURITY_MAX_PER_PASS * 4)
        ]
        await service.evaluate_candidates(mints, now=NOW)
        assert len(evaluator.calls) == settings.TOKEN_SECURITY_MAX_PER_PASS

    async def test_duplicates_are_collapsed_before_the_cap_is_applied(self) -> None:
        service, evaluator, _ = service_with()
        await service.evaluate_candidates(["same"] * 50, now=NOW)
        assert evaluator.calls == ["same"]

    async def test_an_empty_candidate_set_makes_no_call_at_all(self) -> None:
        service, evaluator, _ = service_with()
        assert await service.evaluate_candidates([], now=NOW) == []
        assert evaluator.calls == []


class TestFreshnessIsTheRealRateLimit:
    async def test_a_fresh_evaluation_is_reused_and_costs_no_rpc(self) -> None:
        """The steady state. Most passes should make no call whatsoever."""
        cached = {"mint": fresh_evaluation("mint", NOW)}
        service, evaluator, repository = service_with(cached)
        await service.evaluate_candidates(["mint"], now=NOW + timedelta(minutes=1))
        assert evaluator.calls == []
        assert repository.recorded == []

    async def test_evidence_past_its_own_window_is_re_evaluated(self) -> None:
        stale_at = NOW - CHECK_FRESHNESS[CheckName.VENUE] - timedelta(seconds=1)
        service, evaluator, repository = service_with(
            {"mint": fresh_evaluation("mint", stale_at)}
        )
        await service.evaluate_candidates(["mint"], now=NOW)
        assert evaluator.calls == ["mint"]
        assert repository.recorded == ["mint"]

    def test_the_evaluation_window_is_the_shortest_check_window(self) -> None:
        assert min(CHECK_FRESHNESS.values()) == EVALUATION_FRESHNESS


class TestNoUnboundedFanOut:
    def test_candidates_are_evaluated_sequentially_not_in_a_gather(self) -> None:
        """N mints must be N calls over time, not N sockets at once."""
        source = inspect.getsource(TokenSecurityService.evaluate_candidates)
        assert "gather" not in source
        assert "TaskGroup" not in source

    def test_the_batch_read_is_one_query_not_one_per_mint(self) -> None:
        source = inspect.getsource(TokenSecurityRepository.latest_for_mints)
        assert "for " not in source.split("return")[0].split("rows =")[0].replace(
            "if not mints:", ""
        )
        assert "_latest_per_mint" in source

    def test_the_batch_query_uses_distinct_on_rather_than_a_subquery_per_mint(self) -> None:
        source = inspect.getsource(TokenSecurityRepository._latest_per_mint)
        assert ".distinct(" in source
        assert ".in_(" in source


class TestDisablingTheFeatureCostsNothing:
    async def test_capture_is_a_no_op_when_the_flag_is_off(self, monkeypatch) -> None:
        from app.security import service as security_service

        monkeypatch.setattr(settings, "TOKEN_SECURITY_EVALUATION_ENABLED", False)
        called = False

        class Boom:
            def __init__(self, *args, **kwargs):
                nonlocal called
                called = True

        monkeypatch.setattr(security_service, "TokenSecurityService", Boom)
        await security_service.capture_candidate_security(None, ["a"], now=NOW)
        assert called is False


class TestCacheIsVersionAware:
    """SEC-2 regression: a fresh row from an old evaluator is not reusable."""

    async def test_a_row_from_a_different_evaluator_is_re_evaluated(self) -> None:
        from app.security.contract import EVALUATOR_VERSION

        stale_version = TokenSecurityEvaluation(
            mint_address="mint",
            evaluated_at=NOW,
            overall_status=roll_up(
                (SecurityCheck(name=CheckName.VENUE, status=CheckStatus.PASS),)
            ),
            checks=(SecurityCheck(name=CheckName.VENUE, status=CheckStatus.PASS),),
            evaluator_version="0.0.1-old",
        )
        assert stale_version.is_fresh(now=NOW) is True  # fresh, but unusable
        service, evaluator, repository = service_with({"mint": stale_version})
        await service.evaluate_candidates(["mint"], now=NOW)
        assert evaluator.calls == ["mint"], "an old-version row must not be reused"
        assert repository.recorded == ["mint"]

    async def test_a_row_from_the_current_evaluator_is_still_reused(self) -> None:
        from app.security.contract import EVALUATOR_VERSION

        current = fresh_evaluation("mint", NOW)
        assert current.evaluator_version == EVALUATOR_VERSION
        service, evaluator, _ = service_with({"mint": current})
        await service.evaluate_candidates(["mint"], now=NOW)
        assert evaluator.calls == []
