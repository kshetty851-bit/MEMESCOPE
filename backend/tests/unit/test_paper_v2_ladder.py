"""The V2 ladder's rules, as literals. Pure — no database, no clock.

Every case here is one of the behaviours the brief called out, written so a
failure names the rule it broke rather than "assert False".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.paper_v2.ladder import (
    FillReason,
    LadderRules,
    Quote,
    Rung,
    VARIANT_B,
    resolve,
    settle_unobserved,
)

OPENED = datetime(2026, 8, 22, 0, 0, tzinfo=UTC)
ENTRY = Decimal("1.0")
QTY = Decimal("100")


def q(price: str, minutes: int, *, liq: str = "50000", executable: bool = True) -> Quote:
    return Quote(
        price_usd=Decimal(price),
        captured_at=OPENED + timedelta(minutes=minutes),
        liquidity_usd=Decimal(liq),
        executable=executable,
    )


def run(quotes, *, rules=VARIANT_B, remaining=QTY, already=frozenset()):
    return resolve(
        rules,
        entry_price=ENTRY,
        opened_at=OPENED,
        initial_quantity=QTY,
        remaining_quantity=remaining,
        quotes=quotes,
        already_filled=already,
    )


class TestRungs:
    def test_first_rung_sells_a_quarter_of_the_original(self) -> None:
        out = run([q("1.25", 10)])
        assert len(out.fills) == 1
        assert out.fills[0].quantity == Decimal("25")
        assert out.fills[0].reason is FillReason.TARGET
        assert out.remaining_quantity == Decimal("75")

    def test_a_rung_fills_at_its_own_level_not_the_crossing_print(self) -> None:
        """The published convention: never claim a gap's upside."""
        out = run([q("1.80", 10)])
        prices = [f.price_usd for f in out.fills]
        assert prices == [Decimal("1.25"), Decimal("1.50"), Decimal("1.75")]
        assert all(f.observed_price == Decimal("1.80") for f in out.fills)

    def test_one_observation_may_cross_several_rungs(self) -> None:
        out = run([q("1.80", 10)])
        assert [f.rung_index for f in out.fills] == [0, 1, 2]
        assert out.remaining_quantity == Decimal("25")  # the runner survives

    def test_a_rung_never_fires_twice(self) -> None:
        out = run([q("1.30", 5), q("1.31", 6), q("1.32", 7)])
        assert len(out.fills) == 1

    def test_already_filled_rungs_are_not_replayed(self) -> None:
        """Restart safety: the caller owns the fact, not the price series."""
        out = run([q("1.80", 10)], already=frozenset({0, 1}), remaining=Decimal("50"))
        assert [f.rung_index for f in out.fills] == [2]
        assert out.remaining_quantity == Decimal("25")

    def test_a_rung_does_not_lift_on_a_non_executable_quote(self) -> None:
        out = run([q("2.00", 10, liq="100", executable=False)])
        assert out.fills == ()
        assert out.remaining_quantity == QTY


class TestExpiry:
    @pytest.mark.parametrize(
        ("path", "expected_remaining_sold"),
        [
            ([], Decimal("100")),                    # never reached a rung
            ([("1.25", 10)], Decimal("75")),         # one rung hit
            ([("1.55", 10)], Decimal("50")),         # two
            ([("1.80", 10)], Decimal("25")),         # three; runner left
        ],
    )
    def test_expiry_sells_everything_that_is_left(self, path, expected_remaining_sold) -> None:
        quotes = [q(p, m) for p, m in path] + [q("0.90", 361)]
        out = run(quotes)
        final = out.fills[-1]
        assert final.reason is FillReason.EXPIRY
        assert final.quantity == expected_remaining_sold
        assert out.remaining_quantity == Decimal(0)
        assert out.closed is True

    def test_expiry_fills_at_the_observed_price(self) -> None:
        out = run([q("0.004", 361)])
        assert out.fills[0].price_usd == Decimal("0.004")

    def test_expiry_wins_over_a_rung_in_the_same_reading(self) -> None:
        """Adverse-first. An ambiguous bar does not book the win."""
        out = run([q("2.00", 361)])
        assert [f.reason for f in out.fills] == [FillReason.EXPIRY]

    def test_a_dead_pool_at_expiry_is_labelled_not_dodged(self) -> None:
        out = run([q("0.0001", 361, liq="50", executable=False)])
        assert out.fills[0].reason is FillReason.DEAD_POOL
        assert out.fills[0].price_usd == Decimal("0.0001")
        assert out.closed is True

    def test_a_rug_before_any_rung_loses_the_whole_position(self) -> None:
        out = run([q("0.60", 5), q("0.001", 361)])
        assert len(out.fills) == 1
        assert out.fills[0].quantity == QTY
        assert out.fills[0].price_usd == Decimal("0.001")


class TestUnobserved:
    def test_an_expiry_with_no_observation_is_unsettled_not_invented(self) -> None:
        out = run([q("1.10", 5)])
        assert out.closed is False
        assert out.remaining_quantity == QTY
        tail = settle_unobserved(
            remaining_quantity=out.remaining_quantity,
            last_quote=q("1.10", 5),
            at=OPENED + timedelta(hours=6),
        )
        assert tail is not None
        assert tail.reason is FillReason.UNTRADABLE


class TestRulesAreWellFormed:
    def test_rungs_must_ascend(self) -> None:
        with pytest.raises(ValueError, match="ascend"):
            LadderRules(
                rungs=(
                    Rung(multiple=Decimal("1.5"), fraction=Decimal("0.25")),
                    Rung(multiple=Decimal("1.25"), fraction=Decimal("0.25")),
                ),
                hold_for=timedelta(hours=6),
            )

    def test_a_ladder_cannot_sell_more_than_it_holds(self) -> None:
        with pytest.raises(ValueError, match="sell"):
            LadderRules(
                rungs=(
                    Rung(multiple=Decimal("1.25"), fraction=Decimal("0.6")),
                    Rung(multiple=Decimal("1.50"), fraction=Decimal("0.6")),
                ),
                hold_for=timedelta(hours=6),
            )

    def test_the_published_ladder_keeps_a_quarter_running(self) -> None:
        assert VARIANT_B.runner_fraction == Decimal("0.25")
        assert VARIANT_B.hold_for == timedelta(hours=6)
