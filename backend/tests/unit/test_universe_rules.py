"""The market universe's admission rules.

One test per published rule, because each exists to keep a specific kind of
token out of a wallet whose only exit is a 25% trailing stop.
"""

from __future__ import annotations

from decimal import Decimal

from app.universe import rules
from app.universe.rules import UniverseRow


def _row(**kw: object) -> UniverseRow:
    base = dict(
        mint_address="Mint1111111111111111111111111111111111111111",
        symbol="TEST",
        age_days=30.0,
        liquidity_usd=Decimal("500000"),
        market_cap=Decimal("50000000"),
        holder_count=5000,
    )
    base.update(kw)
    return UniverseRow(**base)  # type: ignore[arg-type]


class TestAge:
    def test_a_token_younger_than_seven_days_is_refused(self) -> None:
        assert rules.judge(_row(age_days=6.9)).reason == "under_7_days"

    def test_seven_days_exactly_is_admitted(self) -> None:
        assert rules.judge(_row(age_days=7.0)).admit

    def test_an_unknown_age_is_refused_rather_than_assumed_old(self) -> None:
        """No age is not the same as old enough."""
        assert rules.judge(_row(age_days=None)).reason == "unknown_age"


class TestLiquidity:
    def test_a_shallow_pool_is_refused(self) -> None:
        assert rules.judge(_row(liquidity_usd=Decimal("1000"))).reason == (
            "liquidity_below_floor"
        )

    def test_an_unknown_liquidity_is_refused(self) -> None:
        assert rules.judge(_row(liquidity_usd=None)).reason == "unknown_liquidity"


class TestStakingDerivatives:
    def test_a_pool_the_size_of_the_float_is_refused(self) -> None:
        """A wrapper or staking token: the pool IS the supply, so it cannot move.

        A 25% trailing stop on an asset that tracks another asset is a
        position that never closes.
        """
        verdict = rules.judge(
            _row(liquidity_usd=Decimal("10000000"), market_cap=Decimal("10000000"))
        )
        assert verdict.reason == "staking_or_wrapped"

    def test_an_ordinary_token_is_not_mistaken_for_one(self) -> None:
        assert rules.judge(
            _row(liquidity_usd=Decimal("500000"), market_cap=Decimal("50000000"))
        ).admit


class TestPeg:
    def test_a_dollar_peg_is_detected(self) -> None:
        assert rules.is_pegged(Decimal("1.0"))
        assert rules.is_pegged(Decimal("0.999"))

    def test_an_ordinary_price_near_a_dollar_is_not_pegged(self) -> None:
        """The band is tight, so a real token that happens to trade near $1
        is still tradeable."""
        assert not rules.is_pegged(Decimal("1.10"))
        assert not rules.is_pegged(Decimal("0.90"))

    def test_no_price_is_not_a_peg(self) -> None:
        assert not rules.is_pegged(None)
        assert not rules.is_pegged(Decimal("0"))


def test_the_cross_source_ratio_catches_the_measured_failures() -> None:
    """The MET-quoted mispricing measured on 2026-08-25 must not pass.

    Values are the real ones: DexScreener's implied market cap against
    Jupiter's for the same mint on the same day.
    """
    measured = [
        ("RAY", Decimal("1098032148683"), Decimal("202960394")),
        ("JUP", Decimal("3638711318036"), Decimal("676435795")),
        ("PUMP", Decimal("23963256451994"), Decimal("1820721832")),
    ]
    for symbol, venue_mcap, reference_mcap in measured:
        assert venue_mcap > reference_mcap * rules.MAX_MARKET_CAP_RATIO, symbol

    # And an ordinary disagreement between two providers still passes.
    assert Decimal("60000000") <= Decimal("50000000") * rules.MAX_MARKET_CAP_RATIO
