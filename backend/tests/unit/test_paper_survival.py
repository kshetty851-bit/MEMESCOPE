"""The survival gate, and the rule that missing data is not safety.

The gate exists because entry depth turned out not to measure exitability: the
collapse cohort entered on a median $150,961 of liquidity and was observing
$1,535 by the time it closed. Turnover separated the two cohorts where depth
did not.

`TestMissingDataIsRejected` is the test that matters most. Treating an
unmeasurable pool as acceptable is how the uncostable trades entered in the
first place, and a gate that fails open is not a gate.
"""

from __future__ import annotations

from decimal import Decimal

from app.paper.survival import (
    EntryObservation,
    Reason,
    Verdict,
    evaluate,
)

SIZE = Decimal(100)


def observation(liq: object, vol: object) -> EntryObservation:
    return EntryObservation(
        liquidity_usd=None if liq is None else Decimal(str(liq)),
        volume_24h_usd=None if vol is None else Decimal(str(vol)),
        size_usd=SIZE,
    )


class TestTurnover:
    def test_healthy_turnover_passes(self) -> None:
        # $150k pool trading $750k a day: turnover 5.0, the band with no
        # collapses in the sample.
        result = evaluate(observation(150_000, 750_000))
        assert result.verdict is Verdict.PASS
        assert result.accepted
        assert result.turnover == Decimal(5)
        assert result.reasons == ()

    def test_the_collapse_signature_is_rejected(self) -> None:
        """A deep pool with almost no flow — the studied failure mode."""
        result = evaluate(observation(150_000, 105_000))  # turnover 0.7
        assert result.verdict is Verdict.REJECT
        assert Reason.TURNOVER_BELOW_FLOOR not in result.reasons
        assert Reason.TURNOVER_MARGINAL in result.reasons

    def test_critical_turnover_gets_its_own_code(self) -> None:
        result = evaluate(observation(150_000, 30_000))  # turnover 0.2
        assert result.verdict is Verdict.REJECT
        assert Reason.TURNOVER_BELOW_FLOOR in result.reasons

    def test_the_boundary_is_inclusive(self) -> None:
        """Exactly at the floor passes: the plateau starts here."""
        result = evaluate(observation(100_000, 100_000))  # turnover 1.0
        assert result.verdict is Verdict.PASS

    def test_depth_alone_does_not_save_a_stagnant_pool(self) -> None:
        """The finding that motivated the gate: deep is not safe."""
        deep_and_dead = evaluate(observation(500_000, 100_000))  # turnover 0.2
        shallow_and_busy = evaluate(observation(8_000, 80_000))  # turnover 10
        assert deep_and_dead.verdict is Verdict.REJECT
        assert shallow_and_busy.accepted


class TestDepth:
    def test_thin_but_busy_pool_is_cautioned_not_refused(self) -> None:
        result = evaluate(observation(4_000, 40_000))  # turnover 10, depth < 5k
        assert result.verdict is Verdict.CAUTION
        assert result.accepted
        assert Reason.DEPTH_BELOW_FLOOR in result.reasons

    def test_thin_and_stagnant_is_refused_on_turnover(self) -> None:
        result = evaluate(observation(4_000, 800))  # turnover 0.2
        assert result.verdict is Verdict.REJECT
        assert Reason.DEPTH_BELOW_FLOOR in result.reasons
        assert Reason.TURNOVER_BELOW_FLOOR in result.reasons

    def test_size_to_liquidity_is_reported(self) -> None:
        result = evaluate(observation(10_000, 100_000))
        assert result.size_to_liquidity == Decimal("0.01")


class TestMissingDataIsRejected:
    """A pool that cannot be measured is not thereby safe."""

    def test_unknown_liquidity_rejects(self) -> None:
        result = evaluate(observation(None, 100_000))
        assert result.verdict is Verdict.REJECT
        assert Reason.LIQUIDITY_UNKNOWN in result.reasons
        assert result.turnover is None

    def test_zero_liquidity_rejects(self) -> None:
        assert evaluate(observation(0, 100_000)).verdict is Verdict.REJECT

    def test_unknown_volume_rejects(self) -> None:
        result = evaluate(observation(100_000, None))
        assert result.verdict is Verdict.REJECT
        assert Reason.VOLUME_UNKNOWN in result.reasons

    def test_zero_volume_is_measured_not_unknown(self) -> None:
        """Zero volume is a real observation, and the worst one."""
        result = evaluate(observation(100_000, 0))
        assert result.verdict is Verdict.REJECT
        assert Reason.TURNOVER_BELOW_FLOOR in result.reasons
        assert result.turnover == Decimal(0)


class TestThresholdsAreParameters:
    def test_sweeping_the_floor_changes_the_verdict(self) -> None:
        obs = observation(100_000, 150_000)  # turnover 1.5
        assert evaluate(obs, min_turnover=Decimal(1)).verdict is Verdict.PASS
        assert evaluate(obs, min_turnover=Decimal(2)).verdict is Verdict.REJECT

    def test_depth_floor_is_tunable(self) -> None:
        obs = observation(6_000, 60_000)
        assert evaluate(obs).verdict is Verdict.PASS
        assert evaluate(obs, min_liquidity_usd=Decimal(10_000)).verdict is Verdict.CAUTION
