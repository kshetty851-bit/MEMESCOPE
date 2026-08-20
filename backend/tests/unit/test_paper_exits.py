"""Exit rules, and the guarantee that the benchmark did not move.

Sprint 26 turned the live wallet's hardcoded bracket into one configuration
among nine. The risk in that refactor is silent: if `exits.resolve` disagrees
with the original `engine.resolve_exit` even slightly, every comparison the lab
draws against Equal Weight v1 is drawn against a benchmark that quietly changed.

So the first class here replays the same histories through both implementations
and demands identical answers. It is the most important test in the sprint.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import product
from typing import ClassVar

import pytest

from app.paper import exits
from app.paper.engine import resolve_exit
from app.paper.models import ExitReason, OpenPosition, Quote

pytestmark = pytest.mark.unit

OPENED = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
ENTRY = Decimal(100)


def quotes(*pairs: tuple[int, str]) -> list[Quote]:
    return [
        Quote(captured_at=OPENED + timedelta(hours=h), price_usd=Decimal(p)) for h, p in pairs
    ]


def legacy_position() -> OpenPosition:
    """A position shaped exactly as the live wallet writes one."""
    return OpenPosition(
        mint_address="probe",
        opened_at=OPENED,
        entry_price=ENTRY,
        quantity=Decimal(1),
        size_usd=Decimal(100),
        target_price=ENTRY * 2,
        stop_price=ENTRY / 2,
        expires_at=OPENED + timedelta(hours=48),
        peak_price=ENTRY,
    )


class TestTheBenchmarkDidNotMove:
    """`exits.BASELINE` must be the live wallet's bracket, exactly."""

    #: Every ordering of a breach, a near-miss and a neutral reading, plus the
    #: ambiguous bar that satisfies two bounds at once.
    PRICES: ClassVar[list[str]] = ["30", "49", "51", "150", "199", "201", "400"]

    @pytest.mark.parametrize("a,b,c", list(product(PRICES, PRICES, PRICES))[:120])
    def test_it_agrees_with_the_original_implementation(self, a: str, b: str, c: str) -> None:
        history = quotes((1, a), (2, b), (3, c))

        old = resolve_exit(legacy_position(), history)
        new, _ = exits.resolve(
            exits.BASELINE, entry_price=ENTRY, opened_at=OPENED, quotes=history
        )

        if old is None:
            assert new is None
            return
        assert new is not None
        assert (old.reason, old.price_usd, old.at) == (new.reason, new.price_usd, new.at)

    def test_expiry_agrees_too(self) -> None:
        history = quotes((47, "150"), (49, "160"))

        old = resolve_exit(legacy_position(), history)
        new, _ = exits.resolve(
            exits.BASELINE, entry_price=ENTRY, opened_at=OPENED, quotes=history
        )

        assert old is not None and new is not None
        assert (old.reason, old.price_usd, old.at) == (new.reason, new.price_usd, new.at)

    def test_the_baseline_numbers_are_the_wallet_numbers(self) -> None:
        """A guard on the constant itself. If someone "improves" these, this
        fails and the comparison table stays honest."""
        from app.paper.strategy import EQUAL_WEIGHT_V1

        assert exits.BASELINE.take_profit_multiple == EQUAL_WEIGHT_V1.take_profit_multiple
        assert exits.BASELINE.stop_loss_multiple == EQUAL_WEIGHT_V1.stop_loss_multiple
        assert exits.BASELINE.hold_for == EQUAL_WEIGHT_V1.hold_for

    def test_exactly_one_strategy_is_the_baseline(self) -> None:
        marked = [s for s in exits.LAB_STRATEGIES if s.is_baseline]
        assert len(marked) == 1
        assert marked[0].id == "equal_weight_v1"


class TestAbsentRules:
    def test_no_rules_at_all_never_closes(self) -> None:
        """Legal and measurable: the position stays open and the replay reports
        it as open rather than inventing a close."""
        found, _ = exits.resolve(
            exits.ExitRules(),
            entry_price=ENTRY,
            opened_at=OPENED,
            quotes=quotes((1, "1"), (2, "9999")),
        )
        assert found is None

    def test_removing_the_stop_lets_a_loser_run(self) -> None:
        rules = exits.ExitRules(take_profit_multiple=Decimal(2), hold_for=timedelta(hours=48))
        found, _ = exits.resolve(
            rules, entry_price=ENTRY, opened_at=OPENED, quotes=quotes((1, "10"))
        )
        assert found is None

    def test_take_profit_only_has_no_deadline(self) -> None:
        found, _ = exits.resolve(
            exits.ExitRules(take_profit_multiple=Decimal(2)),
            entry_price=ENTRY,
            opened_at=OPENED,
            quotes=quotes((500, "150")),
        )
        assert found is None


class TestTrailingStop:
    RULES = exits.ExitRules(trailing_drawdown=Decimal("0.25"))

    def test_it_measures_against_the_high_before_the_reading(self) -> None:
        """A single snapshot cannot both set a new high and fall away from it.
        Treating it as though it could would book an exit at a level never
        observed."""
        found, peak = exits.resolve(
            self.RULES,
            entry_price=ENTRY,
            opened_at=OPENED,
            quotes=quotes((1, "200"), (2, "140")),
        )
        assert found is not None
        assert found.reason is ExitReason.STOP
        # The trigger is 25% below the 200 high, not below the 140 reading...
        assert found.trigger_price == Decimal(150)
        # ...and the fill is the observation that breached it. The trigger says
        # when to sell; it does not find a buyer at 150 when the market printed
        # 140. This is the distinction that used to be collapsed into one field.
        assert found.price_usd == Decimal(140)
        assert peak == Decimal(200)

    def test_it_does_not_fire_inside_the_band(self) -> None:
        found, _ = exits.resolve(
            self.RULES,
            entry_price=ENTRY,
            opened_at=OPENED,
            quotes=quotes((1, "200"), (2, "160")),
        )
        assert found is None

    def test_a_wider_band_holds_a_position_the_tighter_one_exits(self) -> None:
        history = quotes((1, "200"), (2, "140"))
        tight, _ = exits.resolve(
            exits.ExitRules(trailing_drawdown=Decimal("0.25")),
            entry_price=ENTRY,
            opened_at=OPENED,
            quotes=history,
        )
        wide, _ = exits.resolve(
            exits.ExitRules(trailing_drawdown=Decimal("0.40")),
            entry_price=ENTRY,
            opened_at=OPENED,
            quotes=history,
        )
        assert tight is not None
        assert wide is None

    def test_it_trails_from_entry_before_any_high_is_set(self) -> None:
        found, _ = exits.resolve(
            self.RULES, entry_price=ENTRY, opened_at=OPENED, quotes=quotes((1, "70"))
        )
        assert found is not None
        assert found.trigger_price == Decimal(75)
        assert found.price_usd == Decimal(70)


class TestPriority:
    def test_expiry_outranks_every_price_rule(self) -> None:
        rules = exits.ExitRules(
            take_profit_multiple=Decimal(2),
            stop_loss_multiple=Decimal("0.5"),
            hold_for=timedelta(hours=1),
        )
        found, _ = exits.resolve(
            rules, entry_price=ENTRY, opened_at=OPENED, quotes=quotes((2, "500"))
        )
        assert found is not None
        assert found.reason is ExitReason.EXPIRY

    def test_an_ambiguous_bar_resolves_adversely(self) -> None:
        """A reading satisfying both bounds means the price moved further than
        one snapshot can distinguish. Booking the win is not supported."""
        rules = exits.ExitRules(
            take_profit_multiple=Decimal("1.1"), stop_loss_multiple=Decimal("0.9")
        )
        found, _ = exits.resolve(
            rules, entry_price=ENTRY, opened_at=OPENED, quotes=quotes((1, "80"))
        )
        assert found is not None
        assert found.reason is ExitReason.STOP

    def test_the_earliest_breach_wins_across_readings(self) -> None:
        found, _ = exits.resolve(
            exits.BASELINE,
            entry_price=ENTRY,
            opened_at=OPENED,
            quotes=quotes((1, "40"), (2, "500")),
        )
        assert found is not None
        assert found.reason is ExitReason.STOP


class TestPublication:
    def test_every_strategy_publishes_the_rules_it_applies(self) -> None:
        """Derived from the values applied, so the description cannot drift."""
        for strategy in exits.LAB_STRATEGIES:
            published = dict(strategy.published_rules())
            rules = strategy.rules

            if rules.stop_loss_multiple is None:
                assert published["Stop loss"] == "None", strategy.id
            else:
                loss = (1 - rules.stop_loss_multiple) * 100
                assert published["Stop loss"] == f"-{loss:.0f}%", strategy.id

            if rules.hold_for is None:
                assert published["Maximum hold"] == "None", strategy.id

    def test_the_unimplemented_atr_strategy_says_why(self) -> None:
        """An ATR needs OHLC this platform does not store. A proxy under ATR's
        name would be worse than the omission."""
        assert exits.UNAVAILABLE_STRATEGIES
        for _, _, reason in exits.UNAVAILABLE_STRATEGIES:
            assert "true range" in reason.lower() or "ohlc" in reason.lower()

    def test_strategy_ids_are_unique(self) -> None:
        ids = [strategy.id for strategy in exits.LAB_STRATEGIES]
        assert len(ids) == len(set(ids))

    def test_nothing_published_reads_as_advice(self) -> None:
        forbidden = ("you should", "we recommend", "best strategy", "will outperform")
        for strategy in exits.LAB_STRATEGIES:
            text = f"{strategy.name} {strategy.description}".lower()
            for phrase in forbidden:
                assert phrase not in text, strategy.id
