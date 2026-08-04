"""The published strategies, and whether they do what they say.

The wallet's entire claim is "this rule, stated in advance, produced this". That
claim is worth nothing if the published description and the executed code can
drift, so the central test here reads the numbers out of `describe()` and
asserts the trades match them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.paper.models import Candidate
from app.paper.strategy import EQUAL_WEIGHT_V1, FixedSizeStrategy, registry

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def candidate(**overrides: object) -> Candidate:
    base = {
        "mint_address": "probe",
        "rank": 1,
        "price_usd": Decimal("0.01"),
        "observed_at": NOW,
    }
    base.update(overrides)
    return Candidate(**base)  # type: ignore[arg-type]


class TestThePublishedRuleIsTheExecutedRule:
    def test_the_summary_numbers_match_the_trade(self) -> None:
        """If these drift, every figure the wallet reports is described wrongly."""
        spec = EQUAL_WEIGHT_V1.describe()
        rules = {rule.label: rule.value for rule in spec.rules}
        entry = EQUAL_WEIGHT_V1.entry_for(candidate(), cash_available=Decimal(1000), now=NOW)

        assert entry is not None
        assert rules["Trade size"] == f"${entry.size_usd:,.0f}"
        assert rules["Take profit"] == "+100%"
        assert entry.target_price == entry.price_usd * 2
        assert rules["Stop loss"] == "-50%"
        assert entry.stop_price == entry.price_usd / 2
        assert rules["Maximum hold"] == "48 hours"
        assert entry.expires_at == NOW + timedelta(hours=48)

    def test_the_entry_rule_names_the_cut_it_applies(self) -> None:
        spec = EQUAL_WEIGHT_V1.describe()
        rules = {rule.label: rule.value for rule in spec.rules}
        assert str(EQUAL_WEIGHT_V1.top_n) in rules["Entry"]

    def test_nothing_published_reads_as_advice(self) -> None:
        """Rules describe what the simulation does. None of them tells a reader
        what to do, and none predicts."""
        forbidden = ("you should", "we recommend", "will ", "expect", "guarantee")
        for strategy in registry.all():
            spec = strategy.describe()
            text = " ".join(
                [spec.summary, *(f"{r.label} {r.value}" for r in spec.rules)]
            ).lower()
            for phrase in forbidden:
                assert phrase not in text, f"{spec.id}: {phrase}"


class TestEligibility:
    def test_a_token_outside_the_cut_is_declined(self) -> None:
        assert (
            EQUAL_WEIGHT_V1.entry_for(
                candidate(rank=11), cash_available=Decimal(1000), now=NOW
            )
            is None
        )

    def test_short_cash_declines_rather_than_part_filling(self) -> None:
        """A wallet that quietly halved its size would report a return the
        published rule did not produce. Running out of money is a real outcome
        and the equity curve should show it."""
        assert (
            EQUAL_WEIGHT_V1.entry_for(candidate(), cash_available=Decimal(99), now=NOW) is None
        )

    def test_exactly_enough_cash_fills(self) -> None:
        assert (
            EQUAL_WEIGHT_V1.entry_for(candidate(), cash_available=Decimal(100), now=NOW)
            is not None
        )

    def test_an_unpriced_token_is_not_a_free_one(self) -> None:
        for price in (Decimal(0), Decimal("-1")):
            assert (
                EQUAL_WEIGHT_V1.entry_for(
                    candidate(price_usd=price), cash_available=Decimal(1000), now=NOW
                )
                is None
            )

    def test_a_declared_but_non_operational_strategy_never_trades(self) -> None:
        for strategy in registry.all():
            if strategy.operational:
                continue
            assert (
                strategy.entry_for(candidate(), cash_available=Decimal(100_000), now=NOW)
                is None
            ), strategy.id


class TestSizing:
    def test_quantity_is_exact_at_meme_coin_scale(self) -> None:
        """Prices here run to 4.8e-10. Rounding the quantity would misreport the
        exit value of every position."""
        price = Decimal("0.000000000487")
        entry = EQUAL_WEIGHT_V1.entry_for(
            candidate(price_usd=price), cash_available=Decimal(1000), now=NOW
        )
        assert entry is not None
        assert entry.quantity * price == entry.size_usd

    def test_equal_weight_ignores_rank(self) -> None:
        """Any size that varied with the Radar's own opinion would mix a second
        model into a result presented as a test of the first."""
        first = EQUAL_WEIGHT_V1.entry_for(
            candidate(rank=1), cash_available=Decimal(1000), now=NOW
        )
        tenth = EQUAL_WEIGHT_V1.entry_for(
            candidate(rank=10), cash_available=Decimal(1000), now=NOW
        )
        assert first is not None and tenth is not None
        assert first.size_usd == tenth.size_usd


class TestRegistry:
    def test_the_default_is_registered_and_operational(self) -> None:
        assert registry.default.id == EQUAL_WEIGHT_V1.id
        assert registry.default.operational

    def test_exactly_one_strategy_trades(self) -> None:
        """The wallet measures the Radar, not a comparison between rules."""
        assert sum(1 for item in registry.all() if item.operational) == 1

    def test_every_declared_strategy_says_why_it_is_off(self) -> None:
        for strategy in registry.all():
            if not strategy.operational:
                assert strategy.unavailable_reason, strategy.id

    def test_ids_and_versions_are_unique(self) -> None:
        ids = [item.id for item in registry.all()]
        assert len(ids) == len(set(ids))

    def test_an_unregistered_default_is_rejected_at_construction(self) -> None:
        from app.paper.strategy import StrategyRegistry

        with pytest.raises(ValueError, match="not registered"):
            StrategyRegistry((EQUAL_WEIGHT_V1,), default="does_not_exist")

    def test_the_interface_admits_more_than_one_shape(self) -> None:
        """Architecture only, but exercised: a second set of numbers must flow
        through the same code path without a branch."""
        other = FixedSizeStrategy(
            id="probe",
            name="Probe",
            version="9.9.9",
            trade_size_usd=Decimal(25),
            take_profit_multiple=Decimal(3),
            stop_loss_multiple=Decimal("0.8"),
            hold_for=timedelta(hours=12),
            top_n=3,
        )
        entry = other.entry_for(candidate(), cash_available=Decimal(1000), now=NOW)
        assert entry is not None
        assert entry.size_usd == Decimal(25)
        assert entry.target_price == candidate().price_usd * 3
        assert other.describe().rules[6].value == "12 hours"
