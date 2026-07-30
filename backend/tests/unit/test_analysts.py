"""Unit tests for the six analysts and the orchestrator.

The behavioural rules these lock are the ones that would fail silently and
expensively: a veto averaged away, an unavailable analyst scored as zero, or a
recommendation slipping in through prose.
"""

from __future__ import annotations

import ast
import pathlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.analysts import holders, lifecycle, liquidity, momentum, orchestrator, research, risk
from app.analysts.base import AnalystId, Reading
from app.analysts.lifecycle import MissionState
from app.analysts.research import ResearchPriority
from app.radar.models import Observation, RadarSeries

pytestmark = pytest.mark.unit

NOW = datetime(2026, 7, 29, 12, tzinfo=UTC)


def series(
    *,
    count: int = 48,
    price: Decimal = Decimal("0.001"),
    price_step: Decimal = Decimal("0.00002"),
    liquidity_usd: Decimal | None = Decimal(30_000),
    liquidity_step: Decimal = Decimal(200),
    volume: Decimal | None = Decimal(40_000),
    volume_step: Decimal = Decimal(500),
) -> RadarSeries:
    return RadarSeries(
        mint_address="mint",
        observations=[
            Observation(
                captured_at=NOW - timedelta(minutes=(count - i) * 30),
                price_usd=price + price_step * Decimal(i),
                market_cap=Decimal(200_000),
                liquidity_usd=(
                    liquidity_usd + liquidity_step * Decimal(i)
                    if liquidity_usd is not None
                    else None
                ),
                volume_24h=(volume + volume_step * Decimal(i) if volume is not None else None),
                volume_1h=Decimal(1_500),
                buy_count_24h=120,
                sell_count_24h=60,
            )
            for i in range(count)
        ],
    )


class TestUnavailableIsNeverZero:
    def test_holders_reports_null_not_zero(self) -> None:
        # "Cannot see" and "saw nothing" are different claims about a project,
        # and only one of them is about the project.
        reading = holders.analyse(series())
        assert reading.score is None
        assert reading.confidence is None
        assert reading.available is False

    def test_holders_warns_that_silence_is_not_a_clearance(self) -> None:
        reading = holders.analyse(series())
        assert any(
            "silence" in w.message or "clearance" in w.message for w in reading.warnings
        )

    def test_liquidity_refuses_to_score_an_unreported_pool(self) -> None:
        # Missing liquidity is not zero liquidity — the bonding-curve gap.
        reading = liquidity.analyse(series(liquidity_usd=None))
        assert reading.score is None
        assert "absence of data" in reading.reason


class TestConflictResolution:
    def test_a_veto_is_never_averaged_away(self) -> None:
        healthy = series()
        verdict = orchestrator.assess(
            healthy,
            current_multiple=Decimal("2.5"),
            peak_multiple=Decimal("2.5"),
            days_since_detection=Decimal(5),
            has_veto=True,
        )
        assert verdict.mission_state is MissionState.LOST_CONTACT
        assert verdict.priority is ResearchPriority.CRITICAL
        assert "critical" in verdict.summary.lower()

    def test_the_summary_leads_with_risk_not_with_the_good_news(self) -> None:
        verdict = orchestrator.assess(
            series(),
            current_multiple=Decimal("2.5"),
            peak_multiple=Decimal("2.5"),
            days_since_detection=Decimal(5),
            exit_severity="elevated",
        )
        # Technically-complete-but-misleading is the failure mode here.
        assert verdict.summary.startswith("Lost Contact")

    def test_unavailable_analysts_reduce_coverage_rather_than_the_score(self) -> None:
        full = orchestrator.assess(series(), days_since_detection=Decimal(5))
        # Holders is always dark, so coverage can never reach 100.
        assert full.coverage < 100
        assert "Holder Intelligence" in full.unavailable

    def test_confidence_is_capped_by_coverage(self) -> None:
        verdict = orchestrator.assess(series(), days_since_detection=Decimal(5))
        assert verdict.confidence is not None
        assert verdict.confidence <= verdict.coverage


class TestResearchRanksByInformationValue:
    def test_a_deteriorating_project_outranks_a_healthy_quiet_one(self) -> None:
        failing = orchestrator.assess(
            series(),
            current_multiple=Decimal("0.4"),
            peak_multiple=Decimal("3.0"),
            days_since_detection=Decimal(5),
            exit_severity="elevated",
        )
        healthy = orchestrator.assess(
            series(),
            current_multiple=Decimal("1.2"),
            peak_multiple=Decimal("1.25"),
            days_since_detection=Decimal(5),
        )
        order = [
            ResearchPriority.CRITICAL,
            ResearchPriority.HIGH,
            ResearchPriority.MEDIUM,
            ResearchPriority.LOW,
        ]
        assert order.index(failing.priority) < order.index(healthy.priority)

    def test_disagreement_between_analysts_raises_research_value(self) -> None:
        agree = research.analyse(
            {
                AnalystId.LIQUIDITY: Reading(
                    AnalystId.LIQUIDITY, Decimal(60), Decimal(60), "x"
                ),
                AnalystId.MOMENTUM: Reading(AnalystId.MOMENTUM, Decimal(62), Decimal(60), "x"),
            }
        )
        differ = research.analyse(
            {
                AnalystId.LIQUIDITY: Reading(
                    AnalystId.LIQUIDITY, Decimal(95), Decimal(60), "x"
                ),
                AnalystId.MOMENTUM: Reading(AnalystId.MOMENTUM, Decimal(10), Decimal(60), "x"),
            }
        )
        assert differ.score is not None and agree.score is not None
        assert differ.score > agree.score


class TestNoAnalystRecommends:
    def test_no_reason_or_warning_contains_advice(self) -> None:
        # The boundary erodes through prose long before anyone writes "buy".
        verdict = orchestrator.assess(
            series(),
            current_multiple=Decimal("0.4"),
            peak_multiple=Decimal("3.0"),
            days_since_detection=Decimal(5),
            exit_severity="elevated",
            clone_risk="high",
            sharing_name=149,
            has_veto=True,
        )
        prose = " ".join(
            [verdict.summary]
            + [r.reason for r in verdict.readings.values()]
            + [w.message for w in verdict.warnings]
        ).lower()

        # Recommendation *constructions*, not bare words. An earlier version of
        # this test matched " sell " and failed on "never a sell signal" — the
        # Exit Watch disclaimer, which is the opposite of advice. Matching
        # substrings would push the code toward deleting its own safeguards to
        # stay green, which is worse than the leak it was meant to catch.
        for banned in (
            "you should buy",
            "you should sell",
            "we recommend",
            "consider buying",
            "consider selling",
            "worth buying",
            "time to buy",
            "to the moon",
            "guaranteed",
            "will rise",
            "price target",
        ):
            assert banned not in prose, f"advice leaked: {banned!r}"

        # And the disclaimers that make the boundary explicit must survive.
        assert "never a sell signal" in prose
        assert "floor" in prose and "clearance" in prose


class TestDeterminism:
    def test_same_input_same_verdict(self) -> None:
        probe = series()
        runs = {
            str(
                orchestrator.assess(
                    probe,
                    current_multiple=Decimal("1.3"),
                    peak_multiple=Decimal("1.9"),
                    days_since_detection=Decimal(3),
                ).score
            )
            for _ in range(25)
        }
        assert len(runs) == 1

    def test_lifecycle_ordering_puts_collapse_above_a_rising_multiple(self) -> None:
        # Above detection price, but 96% off its peak. The drawdown must win.
        assert (
            lifecycle.classify(
                current_multiple=Decimal("1.1"),
                peak_multiple=Decimal(30),
                days_since_detection=Decimal(5),
                exit_severity=None,
                has_veto=False,
                observations=48,
            )
            is MissionState.LOST_CONTACT
        )

    def test_recon_outranks_lost_contact_without_enough_history(self) -> None:
        # Declaring a project lost on four data points invents certainty.
        assert (
            lifecycle.classify(
                current_multiple=Decimal("0.01"),
                peak_multiple=Decimal(10),
                days_since_detection=Decimal(5),
                exit_severity="elevated",
                has_veto=True,
                observations=3,
            )
            is MissionState.RECON
        )


class TestMomentumDistinguishesSupportedMoves:
    def test_a_rise_on_falling_volume_is_warned_about(self) -> None:
        unsupported = momentum.analyse(series(volume_step=Decimal(-700)))
        codes = {w.code for w in unsupported.warnings}
        assert "MOMENTUM_UNSUPPORTED_BY_VOLUME" in codes

    def test_a_supported_rise_is_not_warned_about(self) -> None:
        supported = momentum.analyse(series())
        codes = {w.code for w in supported.warnings}
        assert "MOMENTUM_UNSUPPORTED_BY_VOLUME" not in codes


class TestRiskIsAFloorNotAClearance:
    def test_every_reading_says_so(self) -> None:
        clean = risk.analyse(series())
        assert "floor" in clean.reason and "clearance" in clean.reason

    def test_higher_is_safer(self) -> None:
        safe = risk.analyse(series())
        dangerous = risk.analyse(series(), has_veto=True, exit_severity="elevated")
        assert safe.score is not None and dangerous.score is not None
        assert dangerous.score < safe.score


def test_analysts_perform_no_io() -> None:
    """The purity guard, matching services/scoring and app/radar.

    Parses every analyst module and fails on an import that would let one reach
    a database, a network or a clock. Adding an I/O dependency here breaks the
    build deliberately.
    """
    forbidden = {
        "sqlalchemy",
        "redis",
        "fastapi",
        "celery",
        "asyncio",
        "random",
        "httpx",
        "requests",
    }
    package = pathlib.Path("app/analysts")

    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root not in forbidden, f"{path.name} imports {alias.name}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                assert root not in forbidden, f"{path.name} imports from {node.module}"
            # datetime.now() would make a reading depend on when it ran.
            elif isinstance(node, ast.Attribute) and node.attr == "now":
                parent = getattr(node.value, "id", "")
                assert parent != "datetime", f"{path.name} reads the clock"
