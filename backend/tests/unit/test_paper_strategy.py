"""The published strategies, and whether they do what they say.

The wallet's entire claim is "this rule, stated in advance, produced this". That
claim is worth nothing if the published description and the executed code can
drift, so the central test here reads the numbers out of `describe()` and
asserts the trades match them.

Generation 2's trailing-stop strategy is live. Retired strategies remain
readable because their archived wallets must still describe the trades they took.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.paper.models import Candidate
from app.paper.strategy import (
    EQUAL_WEIGHT_V1,
    PAPER_TRACK_RECORD_TP125_SL50_V1,
    TRAILING_STOP_25_V1,
    FixedSizeStrategy,
    TrackRecordBracketStrategy,
    TrailingStopStrategy,
    registry,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)

# The bracket tests verify its immutable rule semantics without pretending the
# archived Generation 6 strategy is allowed to open new positions.
BRACKET_FOR_RULE_TEST = TrackRecordBracketStrategy(
    id="test_bracket",
    name="Test bracket",
    version="test",
    trade_size_usd=Decimal(10),
    take_profit_multiple=Decimal("1.25"),
    stop_loss_multiple=Decimal("0.50"),
)


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
        spec = PAPER_TRACK_RECORD_TP125_SL50_V1.describe()
        rules = {rule.label: rule.value for rule in spec.rules}
        entry = BRACKET_FOR_RULE_TEST.entry_for(
            candidate(), cash_available=Decimal(1000), now=NOW
        )

        assert entry is not None
        assert rules["Allocation"] == f"${entry.size_usd:,.0f} per token"
        assert rules["Take profit"] == "1.25x (+25%) from actual entry reference price"
        assert rules["Stop loss"] == "0.50x (-50%) from actual entry reference price"
        assert entry.target_price == Decimal("0.0125")
        assert entry.stop_price == Decimal("0.005")

    def test_the_rules_it_does_not_have_are_published_as_absent(self) -> None:
        """ "None" rather than a number out of reach.

        The forward strategy expresses absent exits as absent values, not
        thresholds at an unreachable value.
        """
        rules = {
            rule.label: rule.value
            for rule in PAPER_TRACK_RECORD_TP125_SL50_V1.describe().rules
        }
        assert rules["Trailing stop"] == "None"
        assert rules["Maximum hold"].startswith("None")

        entry = BRACKET_FOR_RULE_TEST.entry_for(
            candidate(), cash_available=Decimal(1000), now=NOW
        )
        assert entry is not None
        assert entry.target_price is not None
        assert entry.stop_price is not None
        assert entry.expires_at is None

        exits = BRACKET_FOR_RULE_TEST.exit_rules
        assert exits.take_profit_multiple == Decimal("1.25")
        assert exits.stop_loss_multiple == Decimal("0.50")
        assert exits.hold_for is None

    def test_the_observed_gap_fill_assumption_is_published(self) -> None:
        """A gap exits at the quote actually observed, not a theoretical stop."""
        rules = {
            rule.label: rule.value
            for rule in PAPER_TRACK_RECORD_TP125_SL50_V1.describe().rules
        }
        assert "observed triggering price" in rules["Gap execution"].lower()
        assert "paper execution model" in rules["Gap execution"].lower()

    def test_the_entry_rule_states_that_it_reads_raw_discoveries(self) -> None:
        """The active forward experiment accepts each new Track Record admission,
        without a ranking cut."""
        rules = {
            rule.label: rule.value
            for rule in PAPER_TRACK_RECORD_TP125_SL50_V1.describe().rules
        }
        assert PAPER_TRACK_RECORD_TP125_SL50_V1.top_n is None
        assert "track record admission" in rules["Universe"].lower()
        assert "track record" in rules["Admission source"].lower()

    def test_the_retired_bracket_still_describes_itself(self) -> None:
        """Its wallet is archived, not deleted, so its rules must stay readable."""
        spec = EQUAL_WEIGHT_V1.describe()
        rules = {rule.label: rule.value for rule in spec.rules}
        assert rules["Take profit"] == "+100%"
        assert rules["Stop loss"] == "-50%"
        assert rules["Maximum hold"] == "48 hours"
        assert EQUAL_WEIGHT_V1.exit_rules.take_profit_multiple == Decimal(2)
        assert EQUAL_WEIGHT_V1.exit_rules.hold_for == timedelta(hours=48)

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
    def test_rank_never_declines_a_candidate(self) -> None:
        """The whole Radar is in scope, so the hundredth row is as buyable as
        the first when everything above it has already been traded."""
        entry = BRACKET_FOR_RULE_TEST.entry_for(
            candidate(rank=137), cash_available=Decimal(1000), now=NOW
        )
        assert entry is not None

    def test_short_cash_declines_rather_than_part_filling(self) -> None:
        """A wallet that quietly halved its size would report a return the
        published rule did not produce. Running out of money is a real outcome
        and the equity curve should show it."""
        assert (
            BRACKET_FOR_RULE_TEST.entry_for(
                candidate(), cash_available=Decimal("9.99"), now=NOW
            )
            is None
        )

    def test_exactly_enough_cash_fills(self) -> None:
        assert (
            BRACKET_FOR_RULE_TEST.entry_for(
                candidate(), cash_available=Decimal(10), now=NOW
            )
            is not None
        )

    def test_an_unpriced_token_is_not_a_free_one(self) -> None:
        for price in (Decimal(0), Decimal("-1")):
            assert (
                BRACKET_FOR_RULE_TEST.entry_for(
                    candidate(price_usd=price), cash_available=Decimal(1000), now=NOW
                )
                is None
            )

    def test_a_retired_strategy_never_trades(self) -> None:
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
        entry = BRACKET_FOR_RULE_TEST.entry_for(
            candidate(price_usd=price), cash_available=Decimal(1000), now=NOW
        )
        assert entry is not None
        assert entry.quantity * price == entry.size_usd

    def test_equal_weight_ignores_rank(self) -> None:
        """Any size that varied with the Radar's own opinion would mix a second
        model into a result presented as a test of the first."""
        first = BRACKET_FOR_RULE_TEST.entry_for(
            candidate(rank=1), cash_available=Decimal(1000), now=NOW
        )
        hundredth = BRACKET_FOR_RULE_TEST.entry_for(
            candidate(rank=100), cash_available=Decimal(1000), now=NOW
        )
        assert first is not None and hundredth is not None
        assert first.size_usd == hundredth.size_usd

    def test_the_market_is_recorded_and_not_used_to_size(self) -> None:
        """Liquidity gates entry and lands in the audit record. It must never
        change how much is bought — that would be confidence weighting under
        another name."""
        thin = BRACKET_FOR_RULE_TEST.entry_for(
            candidate(liquidity_usd=Decimal(500), market_cap=Decimal(1_000)),
            cash_available=Decimal(1000),
            now=NOW,
        )
        deep = BRACKET_FOR_RULE_TEST.entry_for(
            candidate(liquidity_usd=Decimal(500_000), market_cap=Decimal(9_000_000)),
            cash_available=Decimal(1000),
            now=NOW,
        )
        assert thin is not None and deep is not None
        assert thin.size_usd == deep.size_usd
        assert thin.liquidity_usd == Decimal(500)
        assert deep.market_cap == Decimal(9_000_000)


class TestRegistry:
    def test_the_default_is_the_security_gated_strategy(self) -> None:
        """SEC-2 cutover 2026-08-20, then HOLD-6H the same day.

        Each cutover retires its predecessor and inherits its capital. The
        retired rules are unchanged and still govern the positions opened
        under them — the rules travel on the position row — but new entries
        are taken by the successor, which is still security-gated.
        """
        from app.paper.strategy import (
            SECURITY_GATED_STRATEGY_IDS,
            TRAILING_STOP_25_SECURED_HOLD6H_V3,
            TRAILING_STOP_25_SECURED_V2,
        )

        assert registry.default.id == TRAILING_STOP_25_SECURED_HOLD6H_V3.id
        assert registry.default.operational
        assert registry.default.id in SECURITY_GATED_STRATEGY_IDS
        assert TRAILING_STOP_25_SECURED_V2.operational is False
        assert TRAILING_STOP_25_V1.operational is False

    def test_the_maximum_hold_is_six_hours_and_nothing_else_moved(self) -> None:
        """HOLD-6H: one rule added, every alpha-bearing rule identical.

        Same sizing and same trailing stop as the generation before it, so a
        comparison between the two measures the holding period and not a
        second change smuggled in beside it.
        """
        from app.paper.strategy import (
            TRAILING_STOP_25_SECURED_HOLD6H_V3,
            TRAILING_STOP_25_SECURED_V2,
        )

        assert TRAILING_STOP_25_SECURED_HOLD6H_V3.hold_for == timedelta(hours=6)
        assert TRAILING_STOP_25_SECURED_HOLD6H_V3.exit_rules.hold_for == timedelta(hours=6)
        assert TRAILING_STOP_25_SECURED_V2.hold_for is None
        for field in ("trade_size_usd", "trailing_drawdown", "top_n"):
            assert getattr(TRAILING_STOP_25_SECURED_HOLD6H_V3, field) == getattr(
                TRAILING_STOP_25_SECURED_V2, field
            ), field

        rules = {
            rule.label: rule.value
            for rule in TRAILING_STOP_25_SECURED_HOLD6H_V3.describe().rules
        }
        assert rules["Maximum hold"].startswith("6 hours")

    def test_the_entry_writes_the_cutoff_onto_the_position(self) -> None:
        """The rule travels on the row, so a later change cannot reach back."""
        from app.paper.strategy import TRAILING_STOP_25_SECURED_HOLD6H_V3

        entry = TRAILING_STOP_25_SECURED_HOLD6H_V3.entry_for(
            candidate(), cash_available=Decimal(1000), now=NOW
        )
        assert entry is not None
        assert entry.expires_at == NOW + timedelta(hours=6)
        # And the rules it deliberately does not have stay absent.
        assert entry.target_price is None
        assert entry.stop_price is None

    def test_exactly_one_strategy_trades(self) -> None:
        """The wallet runs one published forward strategy at a time."""
        assert sum(1 for item in registry.all() if item.operational) == 1

    def test_a_second_operational_strategy_is_rejected_at_construction(self) -> None:
        """Sprint 30 removed the selector. A second runnable strategy would be a
        mode nobody chose, and it should fail at import rather than surface as a
        surprise in a wallet's figures.
        """
        from app.paper.strategy import StrategyRegistry

        other = TrailingStopStrategy(
            id="probe",
            name="Probe",
            version="9.9.9",
            trade_size_usd=Decimal(25),
            trailing_drawdown=Decimal("0.10"),
        )
        with pytest.raises(ValueError, match="exactly one strategy"):
            StrategyRegistry((TRAILING_STOP_25_V1, other), default=TRAILING_STOP_25_V1.id)

    def test_every_retired_strategy_says_why_it_is_off(self) -> None:
        for strategy in registry.all():
            if not strategy.operational:
                assert strategy.unavailable_reason, strategy.id

    def test_ids_are_unique(self) -> None:
        ids = [item.id for item in registry.all()]
        assert len(ids) == len(set(ids))

    def test_an_unregistered_default_is_rejected_at_construction(self) -> None:
        from app.paper.strategy import StrategyRegistry

        with pytest.raises(ValueError, match="not registered"):
            StrategyRegistry((TRAILING_STOP_25_V1,), default="does_not_exist")

    def test_the_interface_admits_more_than_one_shape(self) -> None:
        """Architecture only, but exercised: a bracket and a trailing stop must
        both flow through the same entry path without a branch."""
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
